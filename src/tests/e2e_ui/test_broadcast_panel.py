"""
E2E UI tests for the commons broadcast panel.

Per src/rnd/v0.1.7/2026.05.09-inter-session-commons/03-phase2-user-broadcast-design.md
AC8 (panel + confirm modal) — the original AC9 (live aggregate) + AC10 (markdown
preview + DOMPurify) tests were retired 2026-05-13 when Rick removed the
markdown preview pane + the live-aggregate panel from the compose surface.
What's left are the functional flow tests + a new set of compose-row tests
that lock in the 2026-05-13 voice-first layout per the
`2026.05.13-broadcast-stale-bridge-phantom.md` companion redesign.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).

These tests exercise the UI surface only — the backend integration path
(execute_broadcast → listener → ack-watcher) is covered by the in-process
step 9 smoke (`src/tests/smoke/test_broadcast_two_session_e2e.py`).
Here we use `page.route()` to mock the POST endpoint and `page.evaluate()`
to invoke `window.broadcastPanel.handleAck()` directly, so the test runs
fast and deterministically without needing real CC listener sessions.

**XSS-defense coverage moved**: with the live-preview + aggregate panel
retired, body_summary no longer reaches any innerHTML path on this page.
The confirm-modal preview still uses `DOMPurify.sanitize(marked.parse(...))`,
so the script-stripping regression there is covered by
`test_confirm_modal_renders_sanitized_preview` below.
"""

import json

import pytest

from .conftest import BASE_URL


# ─── AC8 — panel + textarea + Send-button gating + confirm modal ───────


class TestBroadcastPanelRendering:
    """AC8: panel renders, Send button gated on body + recipients."""

    def test_panel_present_on_notifications_page( self, notifications_page ):
        """
        The broadcast-submit-card is rendered + toggle button + textarea +
        Send button all in DOM. (2026-05-13: panel was relocated into the
        notifications accordion; test still works via stable testids.)
        """
        card = notifications_page.get_by_test_id( "notifications-broadcast-card" )
        assert card.count() > 0, "broadcast-submit-card not found"

        ta = notifications_page.get_by_test_id( "notifications-broadcast-textarea" )
        assert ta.count() > 0, "broadcast textarea not found"

        btn = notifications_page.get_by_test_id( "notifications-broadcast-send-btn" )
        assert btn.count() > 0, "broadcast send button not found"

        mic = notifications_page.get_by_test_id( "notifications-broadcast-stt-btn" )
        assert mic.count() > 0, "broadcast mic button not found"

    def test_panel_lives_inside_notifications_accordion( self, notifications_page ):
        """
        2026-05-13: panel was relocated from the submit-a-job stack into the
        Claude Code Notifications accordion. Assert the new home so a future
        accidental move-back regresses loudly.
        """
        in_notifications_section = notifications_page.evaluate(
            """() => {
                const card = document.getElementById( 'broadcast-submit-card' );
                if ( !card ) return false;
                const section = document.getElementById( 'notifications-section' );
                return section && section.contains( card );
            }"""
        )
        assert in_notifications_section is True, \
            "broadcast panel must live inside #notifications-section (Claude Code Notifications accordion)"

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


# ─── 2026-05-13 — compose-row layout + voice-first mic (Phase 2 new tests) ─


class TestBroadcastComposeRow:
    """Lock in the 2026-05-13 compose-row redesign: [🎤] [textarea] [Send] on one row."""

    def test_mic_button_sized_like_cc_session_stt( self, notifications_page ):
        """
        Mic button has the marker classes Rick called out as size references:
        `stt-button cc-session-stt`. Computed height matches the cc-session
        row reference (34px).
        """
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        info = notifications_page.evaluate(
            """() => {
                const btn = document.getElementById( 'broadcast-stt-button' );
                if ( !btn ) return null;
                const cs = window.getComputedStyle( btn );
                return {
                    classes: btn.className,
                    height : cs.height,
                    minWidth: cs.minWidth,
                    fontSize: cs.fontSize
                };
            }"""
        )
        assert info is not None, "mic button not found"
        assert "stt-button"      in info[ "classes" ]
        assert "cc-session-stt"  in info[ "classes" ]
        assert info[ "height" ]   == "34px", f"mic height should match cc-session reference 34px, got {info['height']}"
        assert info[ "minWidth" ] == "40px", f"mic min-width should match cc-session reference 40px, got {info['minWidth']}"

    def test_send_button_sized_like_cc_session_send( self, notifications_page ):
        """
        Send button has the marker classes Rick called out: `response-submit-button
        cc-session-send`. Computed height matches the cc-session row reference (34px).
        """
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        info = notifications_page.evaluate(
            """() => {
                const btn = document.getElementById( 'broadcast-send-button' );
                if ( !btn ) return null;
                const cs = window.getComputedStyle( btn );
                return {
                    classes : btn.className,
                    height  : cs.height,
                    fontSize: cs.fontSize,
                    text    : btn.textContent.trim()
                };
            }"""
        )
        assert info is not None, "send button not found"
        assert "response-submit-button" in info[ "classes" ]
        assert "cc-session-send"        in info[ "classes" ]
        assert info[ "height" ] == "34px", f"send height should match cc-session reference 34px, got {info['height']}"
        assert info[ "text" ]   == "Send", f"send button text should be 'Send' (no megaphone, no 'broadcast'), got {info['text']!r}"

    def test_compose_row_dom_order_is_mic_textarea_send( self, notifications_page ):
        """
        DOM children of #broadcast-compose-row are exactly [mic, textarea, send]
        in that left-to-right order. Locks in Rick's flow direction so future
        edits don't shuffle the order.
        """
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        sequence = notifications_page.evaluate(
            """() => {
                const row = document.getElementById( 'broadcast-compose-row' );
                if ( !row ) return null;
                return Array.from( row.children ).map( c => c.id );
            }"""
        )
        assert sequence == [
            "broadcast-stt-button",
            "broadcast-textarea",
            "broadcast-send-button",
        ], f"compose-row order should be [mic, textarea, send], got {sequence!r}"

    def test_retired_preview_and_aggregate_divs_are_gone( self, notifications_page ):
        """
        2026-05-13: live markdown preview pane + aggregate panel + submit-status
        div removed from DOM per Rick. Confirm they're actually gone — a future
        accidental revert would regress the visual artifacts Rick called out.
        """
        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        retired_ids = notifications_page.evaluate(
            """() => ( {
                preview        : !!document.getElementById( 'broadcast-preview' ),
                preview_label  : !!document.getElementById( 'broadcast-preview-label' ),
                submit_status  : !!document.getElementById( 'broadcast-submit-status' ),
                aggregate_panel: !!document.getElementById( 'broadcast-aggregate-panel' ),
                dictate_label  : !!document.getElementById( 'broadcast-voice-input-label' )
            } )"""
        )
        for name, present in retired_ids.items():
            assert present is False, f"#{name.replace('_','-')} should be GONE from DOM, but it's present"


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

    def test_confirm_modal_renders_sanitized_preview( self, notifications_page ):
        """
        T2/T10 regression coverage (moved 2026-05-13 from the retired live-preview tests):
        the confirm modal's preview pane still goes through `DOMPurify.sanitize(marked.parse(...))`,
        so `<script>` in the body is rendered as innocuous markup (or stripped),
        and event-handler attributes (onerror=) are dropped.
        """
        def _route_sessions( route ):
            route.fulfill(
                status       = 200,
                content_type = "application/json",
                body         = json.dumps( {
                    "sessions": [
                        { "session_id": "sess-xss1", "persona_name": "Maria", "persona_icon": "🌸", "persona_color": "#A040A0", "last_seen_iso": None, "conversation_mode_active": False },
                    ]
                } ),
            )
        notifications_page.route( "**/api/commons/active-sessions", _route_sessions )

        notifications_page.evaluate(
            "() => { const s = document.getElementById( 'broadcast-submit-section' );"
            " if ( s.classList.contains( 'collapsed' ) ) toggleSection( 'broadcast-submit-section' ); }"
        )
        notifications_page.evaluate( "() => window.broadcastPanel.refreshSessions()" )
        notifications_page.wait_for_timeout( 400 )

        ta = notifications_page.get_by_test_id( "notifications-broadcast-textarea" )
        ta.fill( "Hello <script>window.__pwnd=true</script> <img src=x onerror=\"alert(1)\"> **bold**" )
        notifications_page.wait_for_timeout( 100 )

        notifications_page.get_by_test_id( "notifications-broadcast-send-btn" ).click()
        notifications_page.wait_for_timeout( 200 )

        modal_preview = notifications_page.evaluate(
            """() => {
                const p = document.querySelector( '#broadcast-confirm-modal .modal-preview' );
                return p ? p.innerHTML : null;
            }"""
        )
        assert modal_preview is not None, "confirm modal must render a preview pane"
        # DOMPurify strips <script> entirely + drops on* handlers + keeps safe markup.
        assert "<script>"    not in modal_preview.lower(), f"<script> survived sanitization: {modal_preview!r}"
        assert "onerror"     not in modal_preview.lower(), f"onerror= survived sanitization: {modal_preview!r}"
        # Verify NO actual execution
        executed = notifications_page.evaluate( "() => window.__pwnd === true" )
        assert executed is False, "T2 violated — <script> in body executed!"

        # Cleanup
        notifications_page.locator( "#broadcast-confirm-modal .btn-cancel" ).click()
        notifications_page.wait_for_timeout( 100 )

    def test_confirm_button_posts_broadcast( self, notifications_page ):
        """Confirm click hits POST /api/commons/broadcast-to-cc-sessions with the textarea content."""
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

        # 2026-05-13: status-text + aggregate-panel divs removed; post-send feedback
        # now flows through the standard notification stream (`commons_broadcast_ack`
        # cards) which is covered by Phase 2's two-session E2E smoke. The POST + modal
        # close + body shape above are the surface this test owns.
