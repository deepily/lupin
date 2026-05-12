"""
E2E UI tests for the commons broadcast panel.

Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md
AC8 (panel + confirm modal) + AC9 (live aggregate) + AC10 (markdown + DOMPurify).

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).

These tests exercise the UI surface only — the backend integration path
(execute_broadcast → listener → ack-watcher) is covered by the in-process
step 9 smoke (`src/tests/smoke/test_broadcast_two_session_e2e.py`).
Here we use `page.route()` to mock the POST endpoint and `page.evaluate()`
to invoke `window.broadcastPanel.handleAck()` directly, so the test runs
fast and deterministically without needing real CC listener sessions.
"""

import json

import pytest

from .conftest import BASE_URL


# ─── AC8 — panel + textarea + Send-button gating + confirm modal ───────


class TestBroadcastPanelRendering:
    """AC8: panel renders, Send button gated on body + recipients."""

    def test_panel_present_on_notifications_page( self, notifications_page ):
        """The broadcast-submit-card is rendered + toggle button + textarea + Send button all in DOM."""
        card = notifications_page.get_by_test_id( "notifications-broadcast-card" )
        assert card.count() > 0, "broadcast-submit-card not found"

        ta = notifications_page.get_by_test_id( "notifications-broadcast-textarea" )
        assert ta.count() > 0, "broadcast textarea not found"

        btn = notifications_page.get_by_test_id( "notifications-broadcast-send-btn" )
        assert btn.count() > 0, "broadcast send button not found"

    def test_send_button_disabled_when_body_empty( self, notifications_page ):
        """AC8 + F17: Send disabled when textarea is empty (no broadcasts of nothing)."""
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        btn = notifications_page.get_by_test_id( "notifications-broadcast-send-btn" )
        assert btn.is_disabled(), "Send button should be disabled with empty body"

    def test_send_button_disabled_when_body_is_whitespace_only( self, notifications_page ):
        """AC8 + F17: Send disabled when textarea contains only whitespace (mirrors endpoint .strip())."""
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        ta = notifications_page.get_by_test_id( "notifications-broadcast-textarea" )
        ta.fill( "   \n  \t  " )
        btn = notifications_page.get_by_test_id( "notifications-broadcast-send-btn" )
        assert btn.is_disabled(), "Send button should be disabled with whitespace-only body"


# ─── AC10 — markdown preview + DOMPurify XSS hardening ─────────────────


class TestBroadcastPreview:
    """AC10 + T2: live preview renders markdown via marked + DOMPurify sanitization."""

    def test_preview_renders_markdown_bold( self, notifications_page ):
        """Bold markdown renders into <strong> in preview."""
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        ta = notifications_page.get_by_test_id( "notifications-broadcast-textarea" )
        ta.fill( "This is **bold** text" )
        notifications_page.wait_for_timeout( 100 )   # debounce-free, but allow input event flush

        preview_html = notifications_page.evaluate(
            "() => document.getElementById( 'broadcast-preview' ).innerHTML"
        )
        assert "<strong>bold</strong>" in preview_html, \
            f"expected <strong>bold</strong> in preview, got: {preview_html!r}"

    def test_preview_strips_script_tags_via_dompurify( self, notifications_page ):
        """T2 regression: <script>alert(1)</script> in body produces preview with script tags removed."""
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        ta = notifications_page.get_by_test_id( "notifications-broadcast-textarea" )
        ta.fill( "Hello <script>alert(1)</script> world" )
        notifications_page.wait_for_timeout( 100 )

        preview_html = notifications_page.evaluate(
            "() => document.getElementById( 'broadcast-preview' ).innerHTML"
        )
        # DOMPurify strips the <script> tag entirely (the standard purify behavior).
        assert "<script>" not in preview_html.lower(), \
            f"<script> tag survived DOMPurify in preview: {preview_html!r}"
        assert "alert(1)" not in preview_html or "<script" not in preview_html.lower(), \
            "script payload should not execute — purify must drop the tag"

    def test_preview_strips_event_handler_attributes( self, notifications_page ):
        """T2 regression: <img onerror="..."> attributes are stripped by DOMPurify."""
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        ta = notifications_page.get_by_test_id( "notifications-broadcast-textarea" )
        ta.fill( '<img src=x onerror="alert(1)">' )
        notifications_page.wait_for_timeout( 100 )

        preview_html = notifications_page.evaluate(
            "() => document.getElementById( 'broadcast-preview' ).innerHTML"
        )
        assert "onerror" not in preview_html.lower(), \
            f"onerror attribute survived DOMPurify: {preview_html!r}"


# ─── AC9 — live aggregate panel ────────────────────────────────────────


class TestBroadcastAggregate:
    """AC9: aggregate panel renders ack events as they arrive + body_summary is text-content (T10)."""

    def test_aggregate_renders_completed_summary( self, notifications_page ):
        """0/2 → 1/2 → 2/2 progression when two acks arrive."""
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        # Seed an in-flight broadcast state via the test hook.
        notifications_page.evaluate(
            """() => window.broadcastPanel._initializeAggregate(
                "bid-test-aggregate",
                [ "sess-maria-aaa", "sess-tiberius-bbb" ],
                2
            )"""
        )
        agg_text_initial = notifications_page.evaluate(
            "() => document.getElementById( 'broadcast-aggregate-panel' ).textContent"
        )
        assert "0/2" in agg_text_initial, f"initial aggregate should read 0/2: {agg_text_initial!r}"

        # First ack — Maria
        notifications_page.evaluate(
            """() => window.broadcastPanel.handleAck( {
                type    : "commons_broadcast_ack",
                payload : {
                    broadcast_id  : "bid-test-aggregate",
                    session_id    : "sess-maria-aaa",
                    persona_name  : "Maria",
                    persona_icon  : "🌸",
                    persona_color : "#A040A0",
                    status        : "completed",
                    body_summary  : "regenerated visual baselines"
                }
            } )"""
        )
        agg_text_one = notifications_page.evaluate(
            "() => document.getElementById( 'broadcast-aggregate-panel' ).textContent"
        )
        assert "1/2" in agg_text_one, f"after first ack should read 1/2: {agg_text_one!r}"
        assert "Maria" in agg_text_one, f"after first ack should name Maria: {agg_text_one!r}"
        assert "regenerated visual baselines" in agg_text_one

        # Second ack — Tiberius
        notifications_page.evaluate(
            """() => window.broadcastPanel.handleAck( {
                type    : "commons_broadcast_ack",
                payload : {
                    broadcast_id  : "bid-test-aggregate",
                    session_id    : "sess-tiberius-bbb",
                    persona_name  : "Tiberius",
                    persona_icon  : "🌑",
                    persona_color : "#3F51B5",
                    status        : "completed",
                    body_summary  : "ran smoke check on master"
                }
            } )"""
        )
        agg_text_full = notifications_page.evaluate(
            "() => document.getElementById( 'broadcast-aggregate-panel' ).textContent"
        )
        assert "All 2 sessions acknowledged" in agg_text_full or "2/2" in agg_text_full, \
            f"after both acks should announce completion: {agg_text_full!r}"
        assert "Tiberius" in agg_text_full
        assert "ran smoke check on master" in agg_text_full

    def test_body_summary_xss_lands_as_text_not_html( self, notifications_page ):
        """T10 regression: body_summary containing <script> is rendered as literal text, NEVER innerHTML."""
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        notifications_page.evaluate(
            """() => window.broadcastPanel._initializeAggregate(
                "bid-test-xss",
                [ "sess-xss" ],
                1
            )"""
        )
        # Inject an ack whose body_summary contains a script tag.
        notifications_page.evaluate(
            """() => window.broadcastPanel.handleAck( {
                type    : "commons_broadcast_ack",
                payload : {
                    broadcast_id  : "bid-test-xss",
                    session_id    : "sess-xss",
                    persona_name  : "Maria",
                    persona_icon  : "🌸",
                    persona_color : "#A040A0",
                    status        : "completed",
                    body_summary  : "<script>window.__pwnd=true</script>OOPS"
                }
            } )"""
        )

        # Confirm the literal `<script>` substring appears as visible TEXT in the panel
        # (which is only possible if the renderer used .textContent, not .innerHTML).
        agg_text = notifications_page.evaluate(
            "() => document.getElementById( 'broadcast-aggregate-panel' ).textContent"
        )
        assert "<script>" in agg_text, \
            f"body_summary should appear as literal text including <script>: {agg_text!r}"

        # And the script must NOT have actually executed.
        executed = notifications_page.evaluate( "() => window.__pwnd === true" )
        assert executed is False, "T10 violated — <script> in body_summary executed!"

        # And the DOM should contain no <script> *element* in the aggregate panel.
        script_count = notifications_page.evaluate(
            "() => document.getElementById( 'broadcast-aggregate-panel' ).querySelectorAll( 'script' ).length"
        )
        assert script_count == 0, "aggregate panel must not contain a real <script> element"


# ─── AC8 — confirm modal + Send → POST flow (mocked) ───────────────────


class TestBroadcastSendFlow:
    """AC8: clicking Send opens the confirm modal; Confirm POSTs; cancel does not."""

    def test_send_opens_confirm_modal_with_recipients( self, notifications_page ):
        """After typing a message and clicking Send, the confirm modal appears with sanitized preview."""
        # Mock GET /api/commons/active-sessions to return 2 fake recipients
        # so the Send button enables. (Real :8000 might have 0 active CC sessions.)
        def _route_sessions( route ):
            route.fulfill(
                status       = 200,
                content_type = "application/json",
                body         = json.dumps( {
                    "sessions": [
                        { "session_id": "sess-aaaaaaaa", "persona_name": "Maria",    "persona_icon": "🌸", "persona_color": "#A040A0", "last_seen_iso": None, "conversation_mode_active": False },
                        { "session_id": "sess-bbbbbbbb", "persona_name": "Tiberius", "persona_icon": "🌑", "persona_color": "#3F51B5", "last_seen_iso": None, "conversation_mode_active": False },
                    ]
                } ),
            )

        notifications_page.route( "**/api/commons/active-sessions", _route_sessions )

        # Trigger refresh after routing is registered.
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        notifications_page.evaluate( "() => window.broadcastPanel.refreshSessions()" )
        notifications_page.wait_for_timeout( 400 )

        ta = notifications_page.get_by_test_id( "notifications-broadcast-textarea" )
        ta.fill( "Run the daily smoke check.\n@Maria: also re-baseline." )
        notifications_page.wait_for_timeout( 100 )

        btn = notifications_page.get_by_test_id( "notifications-broadcast-send-btn" )
        assert not btn.is_disabled(), "Send button should enable with body + 2 recipients"

        btn.click()
        notifications_page.wait_for_timeout( 200 )

        # Modal exists with the confirm button
        modal = notifications_page.locator( "#broadcast-confirm-modal" )
        assert modal.count() == 1, "confirm modal should appear"
        modal_text = modal.text_content()
        assert "Send broadcast to 2 session" in modal_text
        assert "Maria"    in modal_text
        assert "Tiberius" in modal_text

        # Cancel — modal closes without POST
        modal.locator( ".btn-cancel" ).click()
        notifications_page.wait_for_timeout( 100 )
        assert notifications_page.locator( "#broadcast-confirm-modal" ).count() == 0, \
            "Cancel should remove the modal overlay"

    def test_confirm_button_posts_broadcast( self, notifications_page ):
        """Confirm click hits POST /api/commons/broadcast-to-cc-sessions and seeds the aggregate."""
        def _route_sessions( route ):
            route.fulfill(
                status       = 200,
                content_type = "application/json",
                body         = json.dumps( {
                    "sessions": [
                        { "session_id": "sess-cccccccc", "persona_name": "Maria",    "persona_icon": "🌸", "persona_color": "#A040A0", "last_seen_iso": None, "conversation_mode_active": False },
                        { "session_id": "sess-dddddddd", "persona_name": "Tiberius", "persona_icon": "🌑", "persona_color": "#3F51B5", "last_seen_iso": None, "conversation_mode_active": False },
                    ]
                } ),
            )

        broadcast_id = "fed1cafe-1234-4abc-89de-deadbeef1234"
        post_calls   = [ ]

        def _route_broadcast( route ):
            req = route.request
            post_calls.append( req.post_data )
            route.fulfill(
                status       = 200,
                content_type = "application/json",
                body         = json.dumps( {
                    "broadcast_id"      : broadcast_id,
                    "recipients"        : 2,
                    "failed_recipients" : [ ],
                    "status"            : "queued",
                } ),
            )

        notifications_page.route( "**/api/commons/active-sessions",           _route_sessions  )
        notifications_page.route( "**/api/commons/broadcast-to-cc-sessions",  _route_broadcast )

        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        notifications_page.evaluate( "() => window.broadcastPanel.refreshSessions()" )
        notifications_page.wait_for_timeout( 400 )

        ta = notifications_page.get_by_test_id( "notifications-broadcast-textarea" )
        ta.fill( "Smoke check master." )
        notifications_page.wait_for_timeout( 100 )
        notifications_page.get_by_test_id( "notifications-broadcast-send-btn" ).click()
        notifications_page.wait_for_timeout( 200 )

        # Click Confirm
        notifications_page.locator( "#broadcast-confirm-modal .btn-confirm" ).click()
        notifications_page.wait_for_timeout( 500 )

        # POST was made + body included the textarea content
        assert len( post_calls ) == 1, f"expected exactly 1 POST, got {len( post_calls )}"
        posted = json.loads( post_calls[ 0 ] )
        assert posted[ "message" ]            == "Smoke check master."
        assert posted[ "require_ack" ]        is True
        assert posted[ "include_originator" ] is True

        # Modal closed
        assert notifications_page.locator( "#broadcast-confirm-modal" ).count() == 0

        # Status text reflects the broadcast_id prefix
        status_text = notifications_page.get_by_test_id( "notifications-broadcast-status" ).text_content()
        assert "sent to 2 session" in status_text
        assert broadcast_id[ :8 ] in status_text

        # Aggregate panel now tracking 0/2 against the broadcast
        agg_text = notifications_page.evaluate(
            "() => document.getElementById( 'broadcast-aggregate-panel' ).textContent"
        )
        assert "0/2" in agg_text, f"aggregate should show 0/2 after submission: {agg_text!r}"
