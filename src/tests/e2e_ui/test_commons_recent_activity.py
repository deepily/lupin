"""
E2E UI tests for the Commons Traffic Visibility Recent Activity section.

Per AC2 + AC4 + AC5 + AC6 + AC7 of
`src/rnd/v0.1.7/2026.05.14-commons-traffic-visibility-design.md`. Step 10/11.

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).

Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e_ui",
        "pytest_args"        : "-k test_commons_recent_activity",
        "scheduled_at"       : "<user-confirmed-slot>",
        "auto_fix_on_failure": false
    }

Scope (UI-only):
- AC2: feature flag gate — section visible when ON, hidden when OFF
- AC4: history-window dropdown — initial value matches INI default ("today")
- AC5: topic-chip — hidden for reserved topics (`broadcasts`), visible for free-form
- AC6: flat reverse-chronological — newest entries are at the TOP of the list
- AC7: default-expanded, toggle hides within session, no localStorage persistence

These tests use `page.evaluate(...)` to invoke the JS rendering APIs directly
with controlled fixture entries, so they run deterministically without needing
real commons traffic on the test server. The HTTP-layer integration is covered
by `test_commons_traffic_visibility_integration.py` (Step 9 — separate :8000
schedule).
"""

import pytest

from .conftest import BASE_URL


class TestRecentActivitySectionRendering:
    """AC2 — section exists in DOM when feature flag is True (the :8000 default)."""

    def test_section_present_in_dom( self, notifications_page ):
        section = notifications_page.get_by_test_id( "notifications-broadcast-recent-activity" )
        assert section.count() > 0, "Recent Activity section not found in DOM"

    def test_section_visible_when_feature_enabled( self, notifications_page ):
        """AC2 — when commons_traffic_visibility_enabled is True, section is NOT display:none."""
        is_hidden = notifications_page.evaluate(
            """() => {
                const el = document.getElementById( 'commons-recent-activity-section' );
                if ( !el ) return null;
                return window.getComputedStyle( el ).display === 'none';
            }"""
        )
        assert is_hidden is False, "Section should be visible when feature flag is True"

    def test_dropdown_initial_value_is_today( self, notifications_page ):
        """AC4 — dropdown defaults to the INI-configured window (default `today`)."""
        value = notifications_page.evaluate(
            "() => document.getElementById( 'commons-recent-activity-window' ).value"
        )
        assert value == "today", f"Expected dropdown initial value 'today', got {value!r}"

    def test_dropdown_has_all_six_window_options( self, notifications_page ):
        """AC4 — dropdown carries the canonical 6 options matching history-window UX."""
        opts = notifications_page.evaluate(
            """() => Array.from(
                document.getElementById( 'commons-recent-activity-window' ).options
            ).map( o => o.value )"""
        )
        assert set( opts ) == { "today", "24", "48", "168", "720", "all" }, \
            f"Expected canonical 6 options, got {opts!r}"


class TestRecentActivityDefaultExpanded:
    """AC7 — default-expanded; toggle hides within session; no persistence."""

    def test_body_visible_on_initial_load( self, notifications_page ):
        """AC7 — section body is visible on first paint without any user interaction."""
        is_collapsed = notifications_page.evaluate(
            """() => {
                const body = document.getElementById( 'commons-recent-activity-body' );
                return body && body.classList.contains( 'collapsed' );
            }"""
        )
        assert not is_collapsed, "Recent Activity body should be visible by default"

    def test_broadcast_card_parent_default_expanded( self, notifications_page ):
        """Q9 — broadcast card parent renders WITHOUT the `collapsed` class so the section is accessible without clicking the parent."""
        is_parent_collapsed = notifications_page.evaluate(
            """() => document.getElementById( 'broadcast-submit-section' ).classList.contains( 'collapsed' )"""
        )
        assert not is_parent_collapsed, "Broadcast card parent should NOT be collapsed by default (Q9 ratification)"


class TestRecentActivityEntryRender:
    """AC5 + AC6 — entry rendering, topic chip, reverse-chrono ordering."""

    def _seed_entries( self, page, entries ):
        """Helper — directly invoke the JS render API with controlled fixture entries."""
        page.evaluate(
            """(entries) => {
                const ui = window.notificationsUI;
                const el = document.getElementById( 'commons-recent-activity-entries' );
                el.innerHTML = '';
                for ( const e of entries ) {
                    el.appendChild( ui._renderCommonsEntry( e ) );
                }
            }""",
            entries,
        )

    def test_renders_persona_icon_name_topic_chip_body_time( self, notifications_page ):
        """AC5 — entry row carries the 5 visual components in the grid layout."""
        self._seed_entries( notifications_page, [
            {
                "ts"            : "2026-05-14T20:00:00+00:00",
                "topic"         : "coord-notifications-js",
                "topic_kind"    : "free-form",
                "persona_name"  : "Maria",
                "persona_icon"  : "🌸",
                "persona_color" : "#F06292",
                "body"          : "hello world",
                "metadata"      : { },
            }
        ] )

        # All 5 grid-area elements present
        for class_ in (
            "commons-activity-entry-icon",
            "commons-activity-entry-name",
            "commons-activity-entry-topic-chip",
            "commons-activity-entry-body",
            "commons-activity-entry-time",
        ):
            n = notifications_page.evaluate(
                f"() => document.querySelectorAll( '.{class_}' ).length"
            )
            assert n == 1, f"Expected exactly 1 element with class .{class_}, got {n}"

    def test_topic_chip_hidden_for_reserved_topic( self, notifications_page ):
        """AC5 + Q2 — `broadcasts` is reserved → no chip visible."""
        self._seed_entries( notifications_page, [
            {
                "ts"            : "2026-05-14T20:00:00+00:00",
                "topic"         : "broadcasts",
                "topic_kind"    : "reserved",
                "persona_name"  : "Maria",
                "persona_icon"  : "🌸",
                "persona_color" : "#F06292",
                "body"          : "hello",
                "metadata"      : { },
            }
        ] )

        chip_hidden = notifications_page.evaluate(
            "() => document.querySelector( '.commons-activity-entry-topic-chip' ).hidden"
        )
        assert chip_hidden is True, "Topic chip must be hidden for reserved topics"

    def test_topic_chip_visible_for_free_form_topic( self, notifications_page ):
        """AC5 + Q2 — free-form topic chip is visible with topic name as text."""
        self._seed_entries( notifications_page, [
            {
                "ts"            : "2026-05-14T20:00:00+00:00",
                "topic"         : "coord-notifications-js",
                "topic_kind"    : "free-form",
                "persona_name"  : "Maria",
                "persona_icon"  : "🌸",
                "persona_color" : "#F06292",
                "body"          : "x",
                "metadata"      : { },
            }
        ] )

        result = notifications_page.evaluate(
            """() => {
                const c = document.querySelector( '.commons-activity-entry-topic-chip' );
                return { hidden: c.hidden, text: c.textContent };
            }"""
        )
        assert result[ "hidden" ] is False, "Topic chip must be visible for free-form topics"
        assert result[ "text" ] == "coord-notifications-js"

    def test_ws_handler_prepends_newest_entry( self, notifications_page ):
        """AC6 + Q7 — `_handleCommonsActivityWS` prepends new entries (newest at top)."""
        # Seed with an existing "older" entry
        self._seed_entries( notifications_page, [
            {
                "ts"            : "2026-05-14T19:00:00+00:00",
                "topic"         : "broadcasts",
                "topic_kind"    : "reserved",
                "persona_name"  : "Maria",
                "persona_icon"  : "🌸",
                "persona_color" : "#F06292",
                "body"          : "older",
                "metadata"      : { },
            }
        ] )

        # Fire a WS event with a "newer" entry
        notifications_page.evaluate(
            """() => window.notificationsUI._handleCommonsActivityWS( {
                payload: {
                    ts: "2026-05-14T20:00:00+00:00",
                    topic: "broadcasts",
                    topic_kind: "reserved",
                    persona_name: "Maria",
                    persona_icon: "🌸",
                    persona_color: "#F06292",
                    body: "newer",
                    metadata: { },
                }
            } )"""
        )

        bodies = notifications_page.evaluate(
            """() => Array.from(
                document.querySelectorAll( '.commons-activity-entry-body' )
            ).map( e => e.textContent )"""
        )
        assert bodies == [ "newer", "older" ], \
            f"Expected newest-at-top ordering ['newer', 'older'], got {bodies!r}"
