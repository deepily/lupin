"""
E2E UI tests for the commons-activity entry toggle + markdown rendering.

2026-05-16 feature ship (Maria 🌸 session 3c9fce51) — adds:
1. Two-line clamp by default on `.commons-activity-entry-body-content`
2. "Show more ▾" toggle that appears only when content overflows the clamp
3. Markdown rendering via the page-loaded `window.marked` + `window.DOMPurify`
   globals (same pattern as broadcast-panel.js)

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).

Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e",
        "pytest_args"        : "-k test_commons_activity_toggle",
        "scheduled_at"       : "<user-confirmed-slot>",
        "auto_fix_on_failure": false
    }

Scope:
- Long body → content has `.commons-activity-entry-body-content` class, scrollHeight > clientHeight,
  toggle button visible
- Short body → toggle button hidden (no overflow)
- Click toggle → `.expanded` class added to content, button text becomes "Show less ▴"
- Click again → `.expanded` removed, button text returns to "Show more ▾"
- Markdown rendering: `**bold**` produces `<strong>`, `- item` produces `<ul><li>`
- XSS sanitization: `<script>` body does NOT inject executable script

These tests use `page.evaluate(...)` to invoke `_renderCommonsEntry` directly
with controlled fixture entries (same pattern as `test_commons_recent_activity.py`),
so they run deterministically without needing real DM traffic on the test server.
"""

import pytest

from .conftest import BASE_URL


# A long body that's guaranteed to overflow a 2-line clamp at any reasonable
# panel width. Using markdown so the same fixture exercises rendering too.
_LONG_BODY = (
    "**Long DM example** — line one of the message body. "
    "Line two with more text to push past the clamp. "
    "Line three to ensure overflow even at very wide panel widths. "
    "Line four with extra padding for safety. "
    "Line five with a final tail. "
    "Line six just to be sure across font-size variations."
)

_SHORT_BODY = "Just a short ack."

_MARKDOWN_BODY = (
    "**bold** and *italic* and `code`. "
    "Followed by a list:\n"
    "- item one\n"
    "- item two\n"
    "- item three"
)

_XSS_BODY = (
    "Benign prefix. <script>window.__commons_xss_marker = true;</script>"
    " <img src='x' onerror='window.__commons_xss_marker_img = true'>"
    " Trailing text."
)


def _render_entry_via_evaluate( page, body_text: str, with_topic: str = "dm-maria" ):
    """
    Inject a fixture commons-activity entry into the live panel by invoking
    `_renderCommonsEntry` on the notifications controller, then prepending the
    result to the entries container. Returns the entry's outer HTML element ID
    so subsequent assertions can target it deterministically.
    """
    entry_id = "test-commons-entry-fixture"
    page.evaluate(
        """([entryId, body, topic]) => {
            const controller = window.__notifications_controller__ || window.notificationsController;
            if ( !controller || typeof controller._renderCommonsEntry !== 'function' ) {
                throw new Error( '_renderCommonsEntry not available on controller' );
            }
            const entry = {
                ts:             new Date().toISOString(),
                topic:          topic,
                topic_kind:     'free-form',
                sender_session_id: 'fixture-session',
                persona_name:   'Fixture',
                persona_icon:   '🧪',
                persona_color:  '#1c4587',
                body:           body,
                metadata:       { },
            };
            const row = controller._renderCommonsEntry( entry );
            row.id = entryId;
            const entriesEl = document.getElementById( 'commons-recent-activity-entries' );
            if ( entriesEl.firstChild ) {
                entriesEl.insertBefore( row, entriesEl.firstChild );
            } else {
                entriesEl.appendChild( row );
            }
        }""",
        [ entry_id, body_text, with_topic ],
    )
    return entry_id


class TestCommonsActivityLineClamp:
    """Default 2-line clamp on `.commons-activity-entry-body-content`."""

    def test_long_body_overflows_clamp( self, notifications_page ):
        entry_id = _render_entry_via_evaluate( notifications_page, _LONG_BODY )
        # Wait for the requestAnimationFrame measurement to complete
        notifications_page.wait_for_function(
            f"() => document.getElementById('{entry_id}') !== null"
        )
        result = notifications_page.evaluate(
            f"""() => {{
                const row     = document.getElementById('{entry_id}');
                const content = row.querySelector('.commons-activity-entry-body-content');
                return {{
                    has_class: !!content,
                    is_clamped: content.scrollHeight > content.clientHeight + 1,
                    has_expanded_class: content.classList.contains( 'expanded' ),
                }};
            }}"""
        )
        assert result[ "has_class" ], "Inner .commons-activity-entry-body-content must exist"
        assert result[ "is_clamped" ], "Long body must overflow the 2-line clamp"
        assert not result[ "has_expanded_class" ], "Should NOT start expanded by default"

    def test_long_body_shows_toggle_button( self, notifications_page ):
        entry_id = _render_entry_via_evaluate( notifications_page, _LONG_BODY )
        # The requestAnimationFrame measurement reveals the toggle when content overflows
        notifications_page.wait_for_function(
            f"""() => {{
                const row    = document.getElementById('{entry_id}');
                if ( !row ) return false;
                const toggle = row.querySelector('.commons-activity-entry-body-toggle');
                return toggle && !toggle.hidden;
            }}""",
            timeout = 2_000,
        )
        toggle_text = notifications_page.evaluate(
            f"""() => document.getElementById('{entry_id}')
                .querySelector('.commons-activity-entry-body-toggle').textContent.trim()"""
        )
        assert toggle_text.startswith( "Show more" ), (
            f"Initial toggle label should be 'Show more …', got {toggle_text!r}"
        )

    def test_short_body_hides_toggle( self, notifications_page ):
        entry_id = _render_entry_via_evaluate( notifications_page, _SHORT_BODY )
        # Wait briefly for the layout measurement
        notifications_page.wait_for_timeout( 100 )
        is_hidden = notifications_page.evaluate(
            f"""() => {{
                const row    = document.getElementById('{entry_id}');
                const toggle = row.querySelector('.commons-activity-entry-body-toggle');
                return toggle.hidden;
            }}"""
        )
        assert is_hidden, "Short body must NOT show the Show-more toggle"


class TestCommonsActivityToggleBehavior:
    """Click-to-expand + click-to-collapse cycle."""

    def test_click_toggle_expands_content( self, notifications_page ):
        entry_id = _render_entry_via_evaluate( notifications_page, _LONG_BODY )
        notifications_page.wait_for_function(
            f"""() => {{
                const row    = document.getElementById('{entry_id}');
                if ( !row ) return false;
                const toggle = row.querySelector('.commons-activity-entry-body-toggle');
                return toggle && !toggle.hidden;
            }}""",
            timeout = 2_000,
        )
        # Click the toggle
        notifications_page.evaluate(
            f"""() => document.getElementById('{entry_id}')
                .querySelector('.commons-activity-entry-body-toggle').click()"""
        )
        result = notifications_page.evaluate(
            f"""() => {{
                const row     = document.getElementById('{entry_id}');
                const content = row.querySelector('.commons-activity-entry-body-content');
                const toggle  = row.querySelector('.commons-activity-entry-body-toggle');
                return {{
                    is_expanded: content.classList.contains( 'expanded' ),
                    toggle_label: toggle.textContent.trim(),
                    overflow_resolved: content.scrollHeight <= content.clientHeight + 1,
                }};
            }}"""
        )
        assert result[ "is_expanded" ], "Content must carry .expanded class after toggle click"
        assert result[ "toggle_label" ].startswith( "Show less" ), (
            f"Toggle label should flip to 'Show less …', got {result['toggle_label']!r}"
        )
        assert result[ "overflow_resolved" ], "When expanded, content must show fully (no overflow)"

    def test_click_twice_collapses_back( self, notifications_page ):
        entry_id = _render_entry_via_evaluate( notifications_page, _LONG_BODY )
        notifications_page.wait_for_function(
            f"""() => {{
                const row    = document.getElementById('{entry_id}');
                if ( !row ) return false;
                const toggle = row.querySelector('.commons-activity-entry-body-toggle');
                return toggle && !toggle.hidden;
            }}""",
            timeout = 2_000,
        )
        # Click twice
        notifications_page.evaluate(
            f"""() => {{
                const toggle = document.getElementById('{entry_id}')
                    .querySelector('.commons-activity-entry-body-toggle');
                toggle.click();
                toggle.click();
            }}"""
        )
        result = notifications_page.evaluate(
            f"""() => {{
                const row     = document.getElementById('{entry_id}');
                const content = row.querySelector('.commons-activity-entry-body-content');
                const toggle  = row.querySelector('.commons-activity-entry-body-toggle');
                return {{
                    is_expanded: content.classList.contains( 'expanded' ),
                    toggle_label: toggle.textContent.trim(),
                }};
            }}"""
        )
        assert not result[ "is_expanded" ], "Content must collapse back after second click"
        assert result[ "toggle_label" ].startswith( "Show more" ), (
            f"Toggle label should revert to 'Show more …', got {result['toggle_label']!r}"
        )


class TestCommonsActivityMarkdown:
    """Markdown rendering via marked.parse + DOMPurify.sanitize."""

    def test_bold_markdown_produces_strong_element( self, notifications_page ):
        entry_id = _render_entry_via_evaluate( notifications_page, _MARKDOWN_BODY )
        notifications_page.wait_for_function(
            f"() => document.getElementById('{entry_id}') !== null"
        )
        result = notifications_page.evaluate(
            f"""() => {{
                const row     = document.getElementById('{entry_id}');
                const content = row.querySelector('.commons-activity-entry-body-content');
                return {{
                    has_strong: content.querySelector( 'strong' ) !== null,
                    has_em:     content.querySelector( 'em' ) !== null,
                    has_code:   content.querySelector( 'code' ) !== null,
                    has_list:   content.querySelector( 'ul' ) !== null,
                    list_items: content.querySelectorAll( 'ul li' ).length,
                }};
            }}"""
        )
        assert result[ "has_strong" ], "Markdown `**bold**` must render as <strong>"
        assert result[ "has_em" ],     "Markdown `*italic*` must render as <em>"
        assert result[ "has_code" ],   "Markdown `` `code` `` must render as <code>"
        assert result[ "has_list" ],   "Markdown `- item` must render as <ul>"
        assert result[ "list_items" ] == 3, (
            f"Expected 3 <li> children, got {result['list_items']}"
        )


class TestCommonsActivityXSS:
    """DOMPurify sanitization — script tags and onerror handlers must not execute."""

    def test_script_tag_does_not_execute( self, notifications_page ):
        # Clear any prior marker
        notifications_page.evaluate( "() => { delete window.__commons_xss_marker; delete window.__commons_xss_marker_img; }" )
        entry_id = _render_entry_via_evaluate( notifications_page, _XSS_BODY )
        notifications_page.wait_for_function(
            f"() => document.getElementById('{entry_id}') !== null"
        )
        # Give any malicious code a chance to run (it shouldn't)
        notifications_page.wait_for_timeout( 100 )
        result = notifications_page.evaluate(
            """() => ({
                script_executed: window.__commons_xss_marker === true,
                img_handler_executed: window.__commons_xss_marker_img === true,
            })"""
        )
        assert not result[ "script_executed" ], (
            "DOMPurify failed — <script> tag executed (CRITICAL XSS!)"
        )
        assert not result[ "img_handler_executed" ], (
            "DOMPurify failed — <img onerror> handler executed (CRITICAL XSS!)"
        )

    def test_script_tag_stripped_from_innerhtml( self, notifications_page ):
        entry_id = _render_entry_via_evaluate( notifications_page, _XSS_BODY )
        notifications_page.wait_for_function(
            f"() => document.getElementById('{entry_id}') !== null"
        )
        html = notifications_page.evaluate(
            f"""() => document.getElementById('{entry_id}')
                .querySelector('.commons-activity-entry-body-content').innerHTML"""
        )
        assert "<script" not in html.lower(), (
            f"DOMPurify failed — <script> tag remains in DOM: {html!r}"
        )
        # The <img> tag may remain but the onerror attribute MUST be stripped
        # (DOMPurify default behavior).
        assert "onerror" not in html.lower(), (
            f"DOMPurify failed — onerror= handler remains in DOM: {html!r}"
        )
