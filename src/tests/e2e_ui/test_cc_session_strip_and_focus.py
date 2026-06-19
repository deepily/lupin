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
    logged_in_page.goto( f"{BASE_URL}/app/notifications?classic=1" )
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


def _click_hide_inactive_toggle( page ):
    page.locator( "#cc-hide-inactive-toggle" ).click()
    page.wait_for_timeout( 100 )


def _click_strip_icon( page, sender_id ):
    sanitized = sender_id.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
    page.locator( f"#cc-strip-icon-{sanitized}" ).click()
    page.wait_for_timeout( 100 )


def _seed_persona( page, sender_id, color="#E91E63", name="mr radio" ):
    """
    Plant a voice persona for a sender so it counts as "active" under the
    hide-inactive predicate. Mirrors what voice_persona_assigned would do.
    Also patches the existing card root's --persona-color so the
    :not([style*="--persona-color"]) gating fires correctly.
    """
    page.evaluate(
        """( args ) => {
            const ui = window.notificationsUI;
            const persona = {
                name         : args.name,
                display_name : args.name,
                color        : args.color,
                voice_id     : "v_test",
                icon         : "🎙️"
            };
            ui.senderPersonaMap.set( args.senderId, persona );
            // Also patch the card root + strip icon as if voice_persona_assigned fired.
            ui._setPersonaBadgeOnCard( args.senderId, persona );
            ui._applyHideInactiveStripFilter();
        }""",
        { "senderId": sender_id, "color": color, "name": name }
    )
    page.wait_for_timeout( 50 )


def _release_persona( page, sender_id ):
    """Remove a sender's persona, mirroring voice_persona_released."""
    page.evaluate(
        """( sid ) => {
            const ui = window.notificationsUI;
            ui.senderPersonaMap.delete( sid );
            ui._setPersonaBadgeOnCard( sid, null );
            ui._applyHideInactiveStripFilter();
        }""",
        sender_id
    )
    page.wait_for_timeout( 50 )


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

    def test_focused_card_messages_get_height_boost( self, notifications_page_with_strip ):
        """
        Focus-mode height boost (2026-05-30, Speedy 🌿): the focused card's
        per-date message lists (.date-accordion-messages — the real scrollable
        region built by createSenderCard → createDateAccordion) DOUBLE
        (250px → 500px) while focus mode is ON, and revert to 250px when focus
        mode is OFF. Driven purely by the
        body:has(#cc-strip-toggle[data-focus-active="true"]) :has() rule in
        notifications.css — no JS attribute on the card itself.
        """
        page     = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#cccc5555"
        sender_b = "claude.code@lupin.deepily.ai#dddd6666"

        card_a = _inject_cc_sender_card( page, sender_a )
        _inject_cc_sender_card( page, sender_b )

        # The scrollable region only exists once a date accordion is present.
        # Seed one in each card so .date-accordion-messages is in the DOM
        # regardless of which card focus mode lands on.
        for sid in ( sender_a, sender_b ):
            page.evaluate(
                "( sid ) => window.notificationsUI.createDateAccordion( sid, '2026-05-30' )",
                sid
            )
        page.wait_for_timeout( 50 )

        def _messages_max_height( card_id ):
            return page.evaluate(
                """( cardId ) => {
                    const card = document.getElementById( cardId );
                    const msgs = card.querySelector( '.date-accordion-messages' );
                    return msgs ? getComputedStyle( msgs ).maxHeight : null;
                }""",
                card_id
            )

        # Before focus mode: default 250px.
        assert _messages_max_height( card_a ) == "250px", \
            "Outside focus mode the card keeps the 250px default"

        _click_strip_toggle( page )  # enter focus

        # The single visible (focused) card now gets the +50% boost.
        focused_id = page.evaluate(
            """() => {
                const card = Array.from(
                    document.querySelectorAll( '#notifications-list .sender-card' )
                ).find( c => !c.hasAttribute( 'data-focus-hidden' ) );
                return card ? card.id : null;
            }"""
        )
        assert focused_id is not None, "Exactly one focused card must be visible"
        assert _messages_max_height( focused_id ) == "500px", \
            "Focused card message lists must double to 500px (250px × 2) in focus mode"

        _click_strip_toggle( page )  # exit focus

        assert _messages_max_height( card_a ) == "250px", \
            "Exiting focus mode reverts the card to the 250px default"

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

        # The DURABLE persistence layer is localStorage — the focus INTENT must
        # survive the reload regardless of whether any card is hydrated yet.
        stored_after = page.evaluate(
            "() => localStorage.getItem( 'notifications_cc_focus_state' )"
        )
        assert stored_after is not None and "true" in stored_after.lower(), \
            f"Focus intent must persist in localStorage across reload; got {stored_after!r}"

        # NEGATIVE CONTROL (gives this test teeth — it is NOT tautological): the
        # pill's VISUAL restore is deliberately gated on the focused sender's card
        # being present. _restoreCcUiAfterLoad (notifications.js:9933) reverts the
        # pill to OFF when the focused card is absent, PRESERVING the localStorage
        # intent (the 2026-04-30 design + icon-churn-race fix). Immediately after
        # reload the client-only card is gone, so the pill MUST be OFF. If the
        # no-card revert ever regressed (pill wrongly ON without a card), this fails.
        toggle = page.locator( "#cc-strip-toggle" )
        assert toggle.get_attribute( "data-focus-active" ) == "false", \
            "no-card revert must leave the pill OFF right after reload (intent preserved in localStorage, not the visual)"

        # POSITIVE PATH (against the REAL restore logic, not a mock): in production
        # the focused sender's real notifications hydrate its card on reload; this
        # synthetic test re-injects the card to mirror that hydration, then re-runs
        # the genuine post-load restore. If _restoreCcUiAfterLoad's with-card restore
        # regressed (pill stays OFF despite a present focused card), this fails.
        _inject_cc_sender_card( page, sender_a )
        page.evaluate( "() => window.notificationsUI._restoreCcUiAfterLoad()" )
        page.wait_for_timeout( 50 )
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
        assert icon.get_attribute( "data-conv-mode" ) == "speakerphone"

    def test_conv_mode_off_via_ws_clears_strip_icon_overlay( self, notifications_page_with_strip ):
        """
        Regression for the stranded-mic-icon bug (Session a6b318ea, 2026-05-01).

        The speakerphone_changed WS payload carries the full session UUID,
        but strip-icon data-session-id is the 8-char prefix. The WS-router used
        to call _setStripIconConvMode with the un-normalized full UUID, so the
        querySelector missed and the OFF transition never cleared the mic
        overlay. Fix: route the strip-icon update through
        handleConversationModeChanged after normalization.

        This test simulates the full WS path (handleNotificationUpdate switch
        case) for ON then OFF, using the full UUID in the payload, and asserts
        the icon overlay matches the expected state after each transition.

        NOTE (2026-06-10 triage): the live WS event is `speakerphone_changed`
        with `payload.on` (the 2026.05.11 speakerphone refactor — see the
        handleNotificationUpdate case that maps payload.on → conversation_mode_active);
        the retired `conversation_mode_changed`/`payload.active` shape has no switch
        case, so the prior wording drove a DEAD path. Updated to the real contract.

        NOTE (2026-06-10 review, Tiffany): the strip icon is BORN
        data-conv-mode="speakerphone" (notifications.js ~10058-10062 default; the
        fixture does not seed conversationModes for this session), so an ON-first
        assertion is a FALSE POSITIVE — it passes even with the handler neutered.
        Fix: drive OFF first (a genuine speakerphone→quiet transition — the
        stranded-icon clear this test guards), THEN ON (a genuine quiet→speakerphone
        flip). Now NEITHER assertion can pass off the born state.
        """
        page         = notifications_page_with_strip
        sender_a     = "claude.code@lupin.deepily.ai#offtest1"
        session_hash = "offtest1"
        full_uuid    = "offtest1-aaaa-bbbb-cccc-deadbeef0001"  # matches 8-char prefix

        _inject_cc_sender_card( page, sender_a, session_hash=session_hash )
        sanitized = sender_a.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        icon = page.locator( f"#cc-strip-icon-{sanitized}" )

        # OFF FIRST — the icon is born "speakerphone", so on=false is a GENUINE
        # speakerphone→quiet transition (the stranded-icon clear this test guards).
        # Drive the WS-router path with the full UUID (server-canonical shape);
        # handleNotificationUpdate expects a { notification: {...} } envelope. This
        # is the path that used to silently miss (full-UUID vs 8-char-prefix selector).
        page.evaluate(
            """( fullUuid ) => {
                window.notificationsUI.handleNotificationUpdate( {
                    notification: {
                        type    : "speakerphone_changed",
                        payload : { session_id: fullUuid, on: false }
                    }
                } );
            }""",
            full_uuid
        )
        page.wait_for_timeout( 50 )

        assert icon.get_attribute( "data-conv-mode" ) == "quiet", \
            "OFF transition must set data-conv-mode='quiet' (3-state badge since 2026-05-14) — mic icon must not strand"

        # ON — same full UUID, on=true. Now a GENUINE quiet→speakerphone flip (not
        # the born state), so this cannot false-positive if the handler is neutered.
        page.evaluate(
            """( fullUuid ) => {
                window.notificationsUI.handleNotificationUpdate( {
                    notification: {
                        type    : "speakerphone_changed",
                        payload : { session_id: fullUuid, on: true }
                    }
                } );
            }""",
            full_uuid
        )
        page.wait_for_timeout( 50 )

        assert icon.get_attribute( "data-conv-mode" ) == "speakerphone", \
            "ON transition must set data-conv-mode='speakerphone' despite full-UUID payload"


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


# ---------------------------------------------------------------------------
# Regression: bulk-delete + per-day-delete strand strip icons
# ---------------------------------------------------------------------------

class TestStripCleanupOnBulkDelete:
    """
    Regression coverage for the focus-tray-strands-icons bug (Session a6b318ea,
    2026-05-01). Three paths used to tear down sender cards without removing
    their strip icons: clearAllNotifications(), removeSenderCard(),
    clearSenderGroups(). All three now route through _removeStripIcon or
    _clearAllStripIcons.
    """

    def test_clear_all_strip_icons_helper_empties_strip( self, notifications_page_with_strip ):
        """
        _clearAllStripIcons() removes every icon, hides the strip, and resets
        unread counts. Serves as the unit test for the new helper.
        """
        page = notifications_page_with_strip
        for tag in [ "aaaaaaaa", "bbbbbbbb", "cccccccc" ]:
            _inject_cc_sender_card( page, f"claude.code@lupin.deepily.ai#{tag}" )

        assert page.locator( "#cc-strip-icons .cc-strip-icon" ).count() == 3

        page.evaluate( "() => window.notificationsUI._clearAllStripIcons()" )
        page.wait_for_timeout( 50 )

        assert page.locator( "#cc-strip-icons .cc-strip-icon" ).count() == 0
        is_hidden = page.evaluate(
            "() => document.getElementById( 'cc-session-strip' ).hasAttribute( 'hidden' )"
        )
        assert is_hidden, "Strip should hide once the last icon is gone"

        unread_counts = page.evaluate(
            "() => window.notificationsUI.ccStripUnreadCounts"
        )
        assert unread_counts == {}, "Unread counts must reset"

    def test_remove_sender_card_also_removes_strip_icon( self, notifications_page_with_strip ):
        """
        removeSenderCard(senderId) is reached when softDeleteByDate deletes
        the LAST date for a sender. Before the fix it left the strip icon
        stranded; now it must call _removeStripIcon under the hood.
        """
        page     = notifications_page_with_strip
        sender_a = "claude.code@lupin.deepily.ai#removeaaa"
        sender_b = "claude.code@lupin.deepily.ai#removebbb"

        _inject_cc_sender_card( page, sender_a )
        _inject_cc_sender_card( page, sender_b )
        assert page.locator( "#cc-strip-icons .cc-strip-icon" ).count() == 2

        page.evaluate(
            "( sid ) => window.notificationsUI.removeSenderCard( sid )",
            sender_a
        )
        page.wait_for_timeout( 50 )

        sanitized_a = sender_a.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        sanitized_b = sender_b.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )

        assert page.locator( f"#cc-strip-icon-{sanitized_a}" ).count() == 0, \
            "removeSenderCard must take its strip icon with it"
        assert page.locator( f"#cc-strip-icon-{sanitized_b}" ).count() == 1, \
            "Sibling sender's icon must remain"

    def test_clear_sender_groups_wipes_all_strip_icons( self, notifications_page_with_strip ):
        """
        clearSenderGroups() runs when the user changes the history-window
        dropdown. Before the fix it left every strip icon stranded; now it
        must call _clearAllStripIcons.
        """
        page = notifications_page_with_strip
        for tag in [ "history01", "history02", "history03" ]:
            _inject_cc_sender_card( page, f"claude.code@lupin.deepily.ai#{tag}" )
        assert page.locator( "#cc-strip-icons .cc-strip-icon" ).count() == 3

        page.evaluate( "() => window.notificationsUI.clearSenderGroups()" )
        page.wait_for_timeout( 50 )

        assert page.locator( "#cc-strip-icons .cc-strip-icon" ).count() == 0
        is_hidden = page.evaluate(
            "() => document.getElementById( 'cc-session-strip' ).hasAttribute( 'hidden' )"
        )
        assert is_hidden, "Strip should hide after history-window change wipes all senders"

    def test_clear_all_notifications_wipes_strip_icons( self, notifications_page_with_strip ):
        """
        clearAllNotifications() is the "Clear All" button handler. Mock
        window.confirm to return true and stub fetch so the bulk-DELETE
        endpoint isn't actually hit; this isolates the UI behavior under
        test from server state.
        """
        page = notifications_page_with_strip
        for tag in [ "clearaaaa", "clearbbbb" ]:
            _inject_cc_sender_card( page, f"claude.code@lupin.deepily.ai#{tag}" )
        assert page.locator( "#cc-strip-icons .cc-strip-icon" ).count() == 2

        # Stub out confirm() and the bulk-DELETE fetch so the test is
        # purely UI-state — no DB mutation, no auth dependency.
        page.evaluate( """
            () => {
                window.confirm = () => true;
                const realFetch = window.fetch;
                window.fetch = ( url, opts ) => {
                    if ( typeof url === "string" && url.includes( "/api/notifications/bulk/" ) ) {
                        return Promise.resolve( {
                            ok     : true,
                            status : 200,
                            json   : () => Promise.resolve( { deleted_count: 2 } )
                        } );
                    }
                    return realFetch( url, opts );
                };
                // Seed totalCount so clearAllNotifications doesn't early-return.
                for ( const g of window.notificationsUI.senderGroups.values() ) {
                    g.totalCount = 1;
                }
            }
        """ )

        page.evaluate(
            "async () => { await window.notificationsUI.clearAllNotifications(); }"
        )
        page.wait_for_timeout( 200 )

        assert page.locator( "#cc-strip-icons .cc-strip-icon" ).count() == 0, \
            "Clear All must wipe every strip icon"
        is_hidden = page.evaluate(
            "() => document.getElementById( 'cc-session-strip' ).hasAttribute( 'hidden' )"
        )
        assert is_hidden, "Strip should hide after Clear All"


# ---------------------------------------------------------------------------
# Hide-inactive toggle (2026-05-02)
# Design: src/rnd/v0.1.7/2026.05.02-focus-tray-inactive-toggle/01-design.md
# ---------------------------------------------------------------------------

class TestHideInactiveToggle:
    """
    The hide-inactive pill in #cc-session-strip filters out strip icons whose
    senderId has no allocated voice persona (deallocated bridges).
    """

    def test_toggle_pill_present_in_dom( self, notifications_page_with_strip ):
        page = notifications_page_with_strip
        assert page.locator( "#cc-hide-inactive-toggle" ).count() == 1, \
            "Hide-inactive toggle pill should exist alongside the focus toggle"

    def test_toggle_hides_personaless_icons( self, notifications_page_with_strip ):
        """3 icons seeded; 2 with personas, 1 without. Toggle ON → only the
        personaless icon picks up data-inactive-hidden."""
        page = notifications_page_with_strip
        active_a   = "claude.code@lupin.deepily.ai#aaaaaaaa"
        active_b   = "claude.code@lupin.deepily.ai#bbbbbbbb"
        inactive_c = "claude.code@lupin.deepily.ai#cccccccc"
        for sid in [ active_a, active_b, inactive_c ]:
            _inject_cc_sender_card( page, sid )
        _seed_persona( page, active_a, color="#E91E63" )
        _seed_persona( page, active_b, color="#3F51B5" )
        # inactive_c gets no persona

        _click_hide_inactive_toggle( page )

        def hidden( sid ):
            sanitized = sid.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
            return page.evaluate(
                f"() => document.getElementById( 'cc-strip-icon-{sanitized}' )?.getAttribute( 'data-inactive-hidden' )"
            )

        assert hidden( active_a   ) is None,   "Active-A icon must NOT be hidden"
        assert hidden( active_b   ) is None,   "Active-B icon must NOT be hidden"
        assert hidden( inactive_c ) == "true", "Personaless icon MUST be hidden under filter"

    def test_toggle_persists_across_reload( self, notifications_page_with_strip ):
        """Toggle ON, hard reload page, assert toggle is still ON and the
        personaless icon is still hidden."""
        page = notifications_page_with_strip
        active   = "claude.code@lupin.deepily.ai#dddddddd"
        inactive = "claude.code@lupin.deepily.ai#eeeeeeee"
        _inject_cc_sender_card( page, active )
        _inject_cc_sender_card( page, inactive )
        _seed_persona( page, active, color="#E91E63" )

        _click_hide_inactive_toggle( page )

        # Reload the page; localStorage state must survive.
        page.reload()
        page.wait_for_load_state( "networkidle" )

        # Re-seed because in-memory state resets on reload.
        _inject_cc_sender_card( page, active )
        _inject_cc_sender_card( page, inactive )
        _seed_persona( page, active, color="#E91E63" )

        toggle_state = page.evaluate(
            "() => document.getElementById( 'cc-hide-inactive-toggle' ).getAttribute( 'data-hide-inactive' )"
        )
        assert toggle_state == "true", "Toggle should persist ON across reload"

        sanitized = inactive.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        attr = page.evaluate(
            f"() => document.getElementById( 'cc-strip-icon-{sanitized}' )?.getAttribute( 'data-inactive-hidden' )"
        )
        assert attr == "true", "Personaless icon must still be hidden after reload"

    def test_persona_release_hides_icon_when_toggle_on( self, notifications_page_with_strip ):
        """Active session goes inactive (voice_persona_released path) — its
        icon must pick up data-inactive-hidden when the toggle is ON."""
        page = notifications_page_with_strip
        sid = "claude.code@lupin.deepily.ai#ffffffff"
        _inject_cc_sender_card( page, sid )
        _seed_persona( page, sid, color="#E91E63" )

        _click_hide_inactive_toggle( page )

        sanitized = sid.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        # Before release: icon should NOT be hidden (it has a persona)
        before = page.evaluate(
            f"() => document.getElementById( 'cc-strip-icon-{sanitized}' )?.getAttribute( 'data-inactive-hidden' )"
        )
        assert before is None

        _release_persona( page, sid )

        after = page.evaluate(
            f"() => document.getElementById( 'cc-strip-icon-{sanitized}' )?.getAttribute( 'data-inactive-hidden' )"
        )
        assert after == "true", "Icon must hide once its persona is released and toggle is ON"

    def test_persona_assign_unhides_icon_when_toggle_on( self, notifications_page_with_strip ):
        """Inactive icon hidden by toggle — when persona is allocated
        (voice_persona_assigned path) the data-inactive-hidden attr clears."""
        page = notifications_page_with_strip
        sid = "claude.code@lupin.deepily.ai#11111111"
        _inject_cc_sender_card( page, sid )

        _click_hide_inactive_toggle( page )

        sanitized = sid.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        before = page.evaluate(
            f"() => document.getElementById( 'cc-strip-icon-{sanitized}' )?.getAttribute( 'data-inactive-hidden' )"
        )
        assert before == "true", "Personaless icon should be hidden under filter"

        _seed_persona( page, sid, color="#FF9800" )

        after = page.evaluate(
            f"() => document.getElementById( 'cc-strip-icon-{sanitized}' )?.getAttribute( 'data-inactive-hidden' )"
        )
        assert after is None, "Icon must un-hide once a persona is allocated"


# ---------------------------------------------------------------------------
# Bubble differentiation for personaless cards (Option 4 — gray gradient, 2026-05-02)
# Design: src/rnd/v0.1.7/2026.05.02-focus-tray-inactive-toggle/01-design.md §3.2
# ---------------------------------------------------------------------------

class TestPersonalessBubbleGradient:
    """
    Personaless cards (no --persona-color in inline style) render incoming
    bubbles with a visible vertical gray gradient (gray-200 → gray-100). Same
    bubble size, same content, same date/abstract icon layout — only the
    fill changes. Persona-color cards stay untouched.
    """

    def _seed_incoming_messages( self, page, sender_id, count=2 ):
        """Inject `count` incoming messages into the sender card's first
        date accordion so we can assert backgroundImage on real DOM."""
        page.evaluate(
            """( args ) => {
                const ui = window.notificationsUI;
                const today = new Date().toISOString().slice( 0, 10 );
                // The real render path calls ensureDateAccordionExists (notifications.js:18112)
                // BEFORE addMessageToDateAccordion, which early-returns (:12095-12101) if the
                // date-messages container is absent. Mirror that precondition here.
                ui.ensureDateAccordionExists( args.senderId, today );
                for ( let i = 0; i < args.count; i++ ) {
                    ui.addMessageToDateAccordion( args.senderId, today, {
                        id        : `msg-${args.senderId}-${i}`,
                        id_hash   : `msg-${args.senderId}-${i}`,
                        timestamp : new Date().toISOString(),
                        message   : `Message ${i}`,
                        type      : "task"
                    }, false );
                }
            }""",
            { "senderId": sender_id, "count": count }
        )
        page.wait_for_timeout( 100 )

    def test_personaless_card_incoming_has_gray_gradient( self, notifications_page_with_strip ):
        """Personaless card's incoming bubbles use a real gray gradient
        (linear-gradient with two distinct gray stops), not the flat
        near-white wash that the persona-color fallback produces."""
        page = notifications_page_with_strip
        sid = "claude.code@lupin.deepily.ai#22222222"
        _inject_cc_sender_card( page, sid )
        # Do NOT seed persona — this card stays personaless.
        self._seed_incoming_messages( page, sid, count=2 )

        sanitized = sid.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        bg_image = page.evaluate(
            f"""() => {{
                const card = document.getElementById( 'sender-card-{sanitized}' );
                const msg  = card.querySelector( '.date-accordion-messages .sender-message.incoming' );
                return msg ? getComputedStyle( msg ).backgroundImage : null;
            }}"""
        )
        assert bg_image, "Personaless incoming bubble must render a backgroundImage"
        # Real gradient stops, not the same color twice. Browsers serialise
        # the rule as `linear-gradient(to bottom, rgb(233, 236, 239), rgb(248, 249, 250))`
        # — assert both Bootstrap gray-200 and gray-100 are present.
        assert "233, 236, 239" in bg_image, f"gray-200 stop missing: {bg_image!r}"
        assert "248, 249, 250" in bg_image, f"gray-100 stop missing: {bg_image!r}"

    def test_persona_card_incoming_does_not_get_personaless_gradient( self, notifications_page_with_strip ):
        """Persona-color cards keep their existing tinted gradient — the
        personaless override must not fire when --persona-color is set."""
        page = notifications_page_with_strip
        sid = "claude.code@lupin.deepily.ai#33333333"
        _inject_cc_sender_card( page, sid )
        _seed_persona( page, sid, color="#E91E63" )
        self._seed_incoming_messages( page, sid, count=2 )

        sanitized = sid.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        bg_image = page.evaluate(
            f"""() => {{
                const card = document.getElementById( 'sender-card-{sanitized}' );
                const msg  = card.querySelector( '.date-accordion-messages .sender-message.incoming' );
                return msg ? getComputedStyle( msg ).backgroundImage : null;
            }}"""
        )
        assert bg_image, "Persona-color incoming bubble must still render a backgroundImage"
        # Persona-color cards retain the original `rgba(--persona-color-rgb, ...)`
        # gradient. The personaless override stops would inject `233, 236, 239`
        # — that triplet must be absent.
        assert "233, 236, 239" not in bg_image, \
            f"Persona-color card was incorrectly hit by the personaless gradient: {bg_image!r}"

    def test_persona_release_switches_to_gray_gradient( self, notifications_page_with_strip ):
        """Live persona release reapplies the personaless gradient — single
        regression test for the substring-gating selector responding to
        runtime style mutation."""
        page = notifications_page_with_strip
        sid = "claude.code@lupin.deepily.ai#44444444"
        _inject_cc_sender_card( page, sid )
        _seed_persona( page, sid, color="#E91E63" )
        self._seed_incoming_messages( page, sid, count=1 )

        sanitized = sid.replace( "@", "-" ).replace( ".", "-" ).replace( "#", "-" )
        before_release = page.evaluate(
            f"""() => {{
                const card = document.getElementById( 'sender-card-{sanitized}' );
                const msg  = card.querySelector( '.date-accordion-messages .sender-message.incoming' );
                return msg ? getComputedStyle( msg ).backgroundImage : null;
            }}"""
        )
        assert "233, 236, 239" not in before_release, "Pre-release gradient should be persona-tinted"

        _release_persona( page, sid )
        page.wait_for_timeout( 50 )

        after_release = page.evaluate(
            f"""() => {{
                const card = document.getElementById( 'sender-card-{sanitized}' );
                const msg  = card.querySelector( '.date-accordion-messages .sender-message.incoming' );
                return msg ? getComputedStyle( msg ).backgroundImage : null;
            }}"""
        )
        assert "233, 236, 239" in after_release, \
            f"After persona release, bubble should pick up the gray gradient: {after_release!r}"


# ---------------------------------------------------------------------------
# Strip ordering: initial-load preserves API order (newest leftmost)
# ---------------------------------------------------------------------------

class TestStripOrdering:
    """During initial-page-load, _addStripIcon receives insertAtTop=false
    so icons accumulate in API order (newest-first → newest leftmost).
    During runtime, insertAtTop=true so newly-arriving icons land leftmost.
    """

    def test_initial_load_appends_in_api_order( self, notifications_page_with_strip ):
        """Simulate initial-load by toggling isInitialLoad before injecting
        sender cards. The first-injected sender (newest from API) should
        end up leftmost in the strip; the last-injected (oldest) rightmost."""
        page = notifications_page_with_strip
        page.evaluate( "() => { window.notificationsUI.isInitialLoad = true; }" )

        # Inject in API order (newest first, then progressively older).
        ordered = [
            "claude.code@lupin.deepily.ai#newesttt",
            "claude.code@lupin.deepily.ai#middllll",
            "claude.code@lupin.deepily.ai#oldesttt",
        ]
        for sid in ordered:
            _inject_cc_sender_card( page, sid )

        page.evaluate( "() => { window.notificationsUI.isInitialLoad = false; }" )

        # Read DOM order. firstChild = leftmost.
        ids = page.evaluate( """
            () => Array.from(
                document.querySelectorAll( '#cc-strip-icons .cc-strip-icon' )
            ).map( el => el.getAttribute( 'data-sender-id' ) )
        """ )
        assert ids == ordered, \
            f"Initial-load strip ordering should match API order; got {ids!r}, expected {ordered!r}"

    def test_runtime_addition_lands_rightmost( self, notifications_page_with_strip ):
        """Runtime path: a fresh icon APPENDS to the existing strip (newest
        rightmost), so the chronological order (oldest leftmost) holds without
        a re-sort. Design: src/rnd/v0.1.7/2026.05.21-recent-activity-filter-and-focus-bar-chronological-lock.md
        (source comment notifications.js:460-463: "Runtime adds just append")."""
        page = notifications_page_with_strip
        # Seed two icons via the runtime path (default behavior).
        first  = "claude.code@lupin.deepily.ai#aaaaaaa1"
        second = "claude.code@lupin.deepily.ai#bbbbbbb2"
        _inject_cc_sender_card( page, first  )
        _inject_cc_sender_card( page, second )

        # Oldest injection stays leftmost; the newer one appends to the right.
        leftmost = page.evaluate(
            "() => document.querySelector( '#cc-strip-icons .cc-strip-icon' )?.getAttribute( 'data-sender-id' )"
        )
        assert leftmost == first, \
            f"Runtime injection should append rightmost (oldest stays leftmost); got {leftmost!r}, expected {first!r}"


# ---------------------------------------------------------------------------
# Multiplexer WP10 (Lane B / Krishna) — focus-mode 80vh height contract
# ---------------------------------------------------------------------------
#
# Distinct from the legacy /app/notifications 250→500px boost tested above:
# the MULTIPLEXER strip (session-strip.css) overrides the focused card's
# `.date-accordion-messages` from the 60vh baseline (notifications-list.css)
# to **80vh** while focus mode is ON, via the strip selector
#   #cc-session-strip:has( #cc-strip-toggle[data-focus-active="true"] ) ~
#     #notifications-pane .sender-card:not([data-focus-hidden]) .date-accordion-messages
# (NOT the retired FocusTray #focus-mode-toggle — removed in c87f066).
#
# Harness (Clayton review fix, 4bac3ce → this revision): the strip only
# populates from STRIP_STATE_TYPES (SessionStripStore.ts:45) — a plain
# `notification_queue_update` of type 'task' does NOT add a strip icon. So per
# sender we inject the message (builds the card + its .date-accordion-messages)
# AND a `voice_persona_assigned` carrying a non-released voice_persona (adds the
# strip icon), mirroring test_multiplexer_phase6c_section_a_visual.py. Focus is
# entered by clicking the KNOWN sender's strip icon — selected by
# `.cc-strip-icon[data-sender-id=...]` (the multiplexer icon has NO `id` attr;
# it carries data-sender-id per sessionStripIcon.ts:94, so Clayton's
# id-form `#cc-strip-icon-...` is the legacy shape) — NOT the generic
# `#cc-strip-toggle`, which focuses sorted[0] and would measure an ambient
# (hydrated-server) card. We then assert the measured card's identity.
#
# Runtime proof rides the :8000 batch / fresh review (this lane is collect-only).

_MUX_SENDER_A = "wp10-height-a"
_MUX_SENDER_B = "wp10-height-b"

_MUX_INJECT_TWO_SENDERS_JS = """
() => {
    const hook = window.__multiplexerTestHook;
    if ( !hook || !hook.eventBus ) throw new Error( "multiplexer test hook missing" );
    const bus = hook.eventBus;
    const seeds = [
        { id: 'wp10-height-a', ts: '2026-06-10T15:00:00.000Z', msg: 'sender A', name: 'Cheech',  color: '#FFCC80', icon: '🌿' },
        { id: 'wp10-height-b', ts: '2026-06-10T16:00:00.000Z', msg: 'sender B', name: 'Tiberius', color: '#3F51B5', icon: '🌑' },
    ];
    for ( const s of seeds ) {
        // (1) A real message — builds the sender card + its .date-accordion-messages.
        bus.emit({
            type    : 'notification_queue_update',
            payload : { notification: {
                id_hash   : 'n-' + s.id,
                message   : s.msg,
                sender_id : s.id,
                timestamp : s.ts,
                type      : 'task',
            } },
            source : 'wp10-height',
            ts     : 1781449200000,
        });
        // (2) voice_persona_assigned — the ONLY event that adds a strip icon.
        bus.emit({
            type    : 'notification_queue_update',
            payload : { notification: {
                type          : 'voice_persona_assigned',
                sender_id     : s.id,
                timestamp     : s.ts,
                voice_persona : {
                    name        : s.name,
                    voice_id    : 'vid_' + s.id,
                    icon        : s.icon,
                    color       : s.color,
                    borrowed    : false,
                    assigned_at : s.ts,
                },
            } },
            source : 'wp10-height',
            ts     : 1781449260000,
        });
    }
    return true;
}
"""


class TestMultiplexerFocusHeight80vh:
    """WP10 (multiplexer): focus mode boosts the FOCUSED card's message list to 80vh."""

    def test_focused_card_messages_grow_to_80vh_in_focus_mode( self, logged_in_page ):
        page = logged_in_page
        page.goto( f"{BASE_URL}/app/multiplexer" )
        page.wait_for_load_state( "networkidle" )
        page.wait_for_function(
            "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
            timeout=15000,
        )

        page.evaluate( _MUX_INJECT_TWO_SENDERS_JS )
        # Strip reveals (icon added via voice_persona_assigned); the known
        # sender's card + its scrollable per-date region must exist to measure.
        page.wait_for_selector( "#cc-session-strip:not([hidden])", timeout=3000 )
        page.wait_for_selector( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{_MUX_SENDER_A}"]', timeout=3000 )
        card_a = f'#notifications-pane .sender-card[data-sender-id="{_MUX_SENDER_A}"]'
        page.wait_for_selector( f"{card_a} .date-accordion-messages", timeout=3000 )

        def _card_a_max_height():
            return page.evaluate(
                """( sel ) => {
                    const card = document.querySelector( sel );
                    if ( !card ) return null;
                    const msgs = card.querySelector( '.date-accordion-messages' );
                    return msgs ? getComputedStyle( msgs ).maxHeight : null;
                }""",
                card_a,
            )

        def _expected_vh_px( fraction ):
            return page.evaluate( "( f ) => Math.round( window.innerHeight * f )", fraction )

        def _px( value ):
            return float( value.replace( "px", "" ) )

        # Baseline (focus OFF): 60vh default from notifications-list.css.
        before = _card_a_max_height()
        assert before is not None, "sender A's .date-accordion-messages must exist to measure"
        assert abs( _px( before ) - _expected_vh_px( 0.60 ) ) <= 2, \
            f"outside focus mode the multiplexer card keeps the 60vh baseline; got {before}"

        # Enter focus on the KNOWN sender by clicking ITS strip icon (not the
        # generic toggle — that would focus sorted[0], an ambient card).
        page.locator( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{_MUX_SENDER_A}"]' ).click()
        page.wait_for_selector( '#cc-strip-toggle[data-focus-active="true"]', timeout=2000 )

        # The single visible (not focus-hidden) card must be the one we injected.
        focused_sender = page.evaluate(
            """() => {
                const card = Array.from(
                    document.querySelectorAll( '#notifications-pane .sender-card' )
                ).find( c => !c.hasAttribute( 'data-focus-hidden' ) );
                return card ? card.getAttribute( 'data-sender-id' ) : null;
            }"""
        )
        assert focused_sender == _MUX_SENDER_A, \
            f"focus must land on the injected sender, not an ambient card; got {focused_sender!r}"

        boosted = _card_a_max_height()
        assert abs( _px( boosted ) - _expected_vh_px( 0.80 ) ) <= 2, \
            f"focused card message list must grow to 80vh in focus mode; got {boosted}"

        # Exit focus (click the focused icon again) → revert to the 60vh baseline.
        page.locator( f'#cc-strip-icons .cc-strip-icon[data-sender-id="{_MUX_SENDER_A}"]' ).click()
        page.wait_for_selector( '#cc-strip-toggle[data-focus-active="false"]', timeout=2000 )
        after = _card_a_max_height()
        assert abs( _px( after ) - _expected_vh_px( 0.60 ) ) <= 2, \
            f"exiting focus mode reverts to the 60vh baseline; got {after}"
