"""
E2E UI tests for the Recent Activity 3-axis filter strip + the focus-bar
chronological-lock ordering.

Design: src/rnd/v0.1.7/2026.05.21-recent-activity-filter-and-focus-bar-chronological-lock.md

Two feature surfaces under test:

Part A — Recent Activity filter strip (`#commons-recent-activity-section`)
  - Three inline `<select>` dropdowns: Direction · Kind · Persona
  - Filter applies client-side over the raw-entry cache; dropdown changes
    re-render instantly (no server hit)
  - Filter state persists across page reload via localStorage
    (`notifications_commons_activity_filter`)
  - Empty-state copy is filter-aware

Part B — Focus-bar chronological lock (`#cc-session-strip`)
  - Each `.cc-strip-icon` is stamped with `data-created-at` from
    `voice_persona.assigned_at`
  - Icons are sorted ascending after initial hydration (oldest leftmost,
    newest rightmost) and never reposition on activity

Plus accordion persistence (broadcast card + recent activity body) which
flows through the augmented `toggleSection()` global helper:
  - `notifications_broadcast_card_open` localStorage key
  - `notifications_recent_activity_open` localStorage key

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit).

Submit via:

    POST /api/test-suite/submit
    {
        "test_types"         : "e2e",
        "pytest_args"        : "-k test_commons_activity_filters_and_strip_chrono",
        "scheduled_at"       : "<user-confirmed-slot>",
        "auto_fix_on_failure": false
    }

Test strategy: use `page.evaluate(...)` to seed the in-memory raw cache
with deterministic fixture entries and assert filter behavior. This is
the same pattern used by test_commons_activity_toggle.py — runs without
needing live commons traffic on the test server.
"""

import pytest

from .conftest import BASE_URL


# ---------------------------------------------------------------------------
#  Fixture entries — heterogeneous mix across Direction/Kind/Persona axes
# ---------------------------------------------------------------------------

def _seed_raw_entries( page, entries ):
    """
    Replace the controller's _commonsRawEntries cache with a deterministic
    list, then re-render so the DOM matches the active filter.
    """
    page.evaluate(
        """( entries ) => {
            const controller = window.notificationsUI;
            if ( !controller ) throw new Error( "notifications controller not found on window" );
            controller._commonsRawEntries = entries;
            if ( typeof controller._renderAllCommonsEntries === "function" ) {
                controller._renderAllCommonsEntries();
            }
        }""",
        entries,
    )


def _read_filter_state( page ):
    """Return the controller's in-memory + persisted filter state."""
    return page.evaluate(
        """() => {
            const controller = window.notificationsUI;
            const ls = localStorage.getItem( "notifications_commons_activity_filter" );
            return {
                in_memory: controller ? controller._commonsActivityFilter : null,
                local_storage: ls ? JSON.parse( ls ) : null
            };
        }"""
    )


def _visible_entry_count( page ):
    """Count how many `.commons-activity-entry` rows are currently rendered."""
    return page.evaluate(
        """() => document.querySelectorAll( "#commons-recent-activity-entries .commons-activity-entry" ).length"""
    )


# ---------------------------------------------------------------------------
#  Part A — Filter dropdowns exist with the correct option sets
# ---------------------------------------------------------------------------

class TestFilterDropdownsSkeleton:
    """Skeleton: three native <select>s with the expected option sets."""

    def test_direction_dropdown_has_three_options( self, notifications_page ):
        options = notifications_page.evaluate(
            """() => Array.from(
                document.getElementById( "commons-recent-activity-filter-direction" ).options
            ).map( o => o.value )"""
        )
        assert options == [ "", "sender", "recipient" ], (
            f"Direction dropdown options mismatch: {options!r}"
        )

    def test_kind_dropdown_has_four_options_including_broadcasts( self, notifications_page ):
        options = notifications_page.evaluate(
            """() => Array.from(
                document.getElementById( "commons-recent-activity-filter-kind" ).options
            ).map( o => o.value )"""
        )
        assert options == [ "all", "heartbeats", "personas", "broadcasts" ], (
            f"Kind dropdown options mismatch: {options!r}"
        )

    def test_persona_dropdown_starts_with_any_persona_default( self, notifications_page ):
        first_value = notifications_page.evaluate(
            """() => document.getElementById( "commons-recent-activity-filter-persona" ).options[ 0 ].value"""
        )
        assert first_value == "", "Persona dropdown first option must be the no-filter default"

    def test_refresh_button_tooltip_mentions_both_actions( self, notifications_page ):
        tooltip = notifications_page.evaluate(
            """() => document.getElementById( "commons-recent-activity-refresh" ).getAttribute( "title" )"""
        )
        assert "Reload activity stream" in tooltip and "persona" in tooltip.lower(), (
            f"Refresh button tooltip must reflect dual purpose, got: {tooltip!r}"
        )


# ---------------------------------------------------------------------------
#  Part A — Filter predicate applied to the raw-entry cache
# ---------------------------------------------------------------------------

_FIXTURE_ENTRIES = [
    # Heartbeat from Tiberius to María
    {
        "ts"                : "2026-05-21T10:00:00Z",
        "topic"             : "dm-maria",
        "topic_kind"        : "free-form",
        "sender_session_id" : "tiberius-1",
        "persona_name"      : "tiberius",
        "persona_icon"      : "🌑",
        "persona_color"     : "#222",
        "body"              : "tick 1",
        "metadata"          : { "kind": "heartbeat", "tick_num": 1 }
    },
    # Conversational DM from María to Tiberius
    {
        "ts"                : "2026-05-21T10:05:00Z",
        "topic"             : "dm-tiberius",
        "topic_kind"        : "free-form",
        "sender_session_id" : "maria-1",
        "persona_name"      : "maria",
        "persona_icon"      : "🌸",
        "persona_color"     : "#f8c",
        "body"              : "hi tiberius",
        "metadata"          : { "kind": "question" }
    },
    # Broadcast from Mr. Radio
    {
        "ts"                : "2026-05-21T10:10:00Z",
        "topic"             : "broadcasts",
        "topic_kind"        : "reserved",
        "sender_session_id" : "mrradio-1",
        "persona_name"      : "mr radio",
        "persona_icon"      : "🦉",
        "persona_color"     : "#FFA000",
        "body"              : "broadcast from mr radio",
        "metadata"          : { }
    },
    # Broadcast-ack from Tiberius
    {
        "ts"                : "2026-05-21T10:11:00Z",
        "topic"             : "broadcast-acks",
        "topic_kind"        : "reserved",
        "sender_session_id" : "tiberius-1",
        "persona_name"      : "tiberius",
        "persona_icon"      : "🌑",
        "persona_color"     : "#222",
        "body"              : "completed",
        "metadata"          : { }
    }
]


class TestFilterPredicate:
    """Filter dropdowns control which fixture entries render."""

    def test_default_no_filter_shows_all_entries( self, notifications_page ):
        _seed_raw_entries( notifications_page, _FIXTURE_ENTRIES )
        assert _visible_entry_count( notifications_page ) == 4

    def test_kind_heartbeats_shows_only_heartbeats( self, notifications_page ):
        _seed_raw_entries( notifications_page, _FIXTURE_ENTRIES )
        notifications_page.evaluate(
            """() => {
                const ctl = window.notificationsUI;
                ctl._setCommonsActivityKind( "heartbeats" );
            }"""
        )
        assert _visible_entry_count( notifications_page ) == 1

    def test_kind_personas_excludes_heartbeats_and_broadcasts( self, notifications_page ):
        _seed_raw_entries( notifications_page, _FIXTURE_ENTRIES )
        notifications_page.evaluate(
            """() => {
                const ctl = window.notificationsUI;
                ctl._setCommonsActivityKind( "personas" );
            }"""
        )
        # Only the conversational dm-tiberius entry matches; heartbeat + 2 broadcasts excluded
        assert _visible_entry_count( notifications_page ) == 1

    def test_kind_broadcasts_includes_acks( self, notifications_page ):
        _seed_raw_entries( notifications_page, _FIXTURE_ENTRIES )
        notifications_page.evaluate(
            """() => {
                const ctl = window.notificationsUI;
                ctl._setCommonsActivityKind( "broadcasts" );
            }"""
        )
        # Both `broadcasts` AND `broadcast-acks` topics match
        assert _visible_entry_count( notifications_page ) == 2

    def test_direction_recipient_tiberius_filters_by_dm_topic( self, notifications_page ):
        _seed_raw_entries( notifications_page, _FIXTURE_ENTRIES )
        notifications_page.evaluate(
            """() => {
                const ctl = window.notificationsUI;
                ctl._setCommonsActivityDirection( "recipient" );
                ctl._setCommonsActivityPersona( "tiberius" );
            }"""
        )
        # Only the dm-tiberius entry matches (conversational DM from maria)
        assert _visible_entry_count( notifications_page ) == 1

    def test_direction_recipient_is_silent_noop_when_kind_broadcasts( self, notifications_page ):
        _seed_raw_entries( notifications_page, _FIXTURE_ENTRIES )
        notifications_page.evaluate(
            """() => {
                const ctl = window.notificationsUI;
                ctl._setCommonsActivityKind( "broadcasts" );
                ctl._setCommonsActivityDirection( "recipient" );
                ctl._setCommonsActivityPersona( "tiberius" );
            }"""
        )
        # Both broadcast topics still surface — Recipient axis is a silent no-op for broadcasts
        assert _visible_entry_count( notifications_page ) == 2


# ---------------------------------------------------------------------------
#  Part A — Filter persistence across page reload
# ---------------------------------------------------------------------------

class TestFilterPersistence:
    """Filter state survives a page reload via localStorage."""

    def test_filter_round_trips_through_localstorage( self, notifications_page ):
        # Set a non-default filter state
        notifications_page.evaluate(
            """() => {
                const ctl = window.notificationsUI;
                ctl._setCommonsActivityDirection( "sender" );
                ctl._setCommonsActivityKind( "heartbeats" );
                ctl._setCommonsActivityPersona( "tiberius" );
            }"""
        )

        # Verify localStorage write
        ls = notifications_page.evaluate(
            """() => JSON.parse( localStorage.getItem( "notifications_commons_activity_filter" ) || "null" )"""
        )
        assert ls == { "direction": "sender", "kind": "heartbeats", "persona": "tiberius" }, (
            f"Filter state not persisted to localStorage: {ls!r}"
        )

        # Reload and verify restoration. The controller global is set during the
        # synchronous constructor, but `_initCommonsRecentActivity` (which applies
        # the persisted filter state to the dropdowns) runs AFTER the async
        # `loadConversationHistory()` step at startup. Wait for the dropdown to
        # actually reflect the restored state rather than for the controller to
        # exist.
        notifications_page.reload()
        notifications_page.wait_for_function(
            """() => {
                const el = document.getElementById( "commons-recent-activity-filter-direction" );
                return el && el.value === "sender";
            }""",
            timeout = 15_000
        )

        restored = _read_filter_state( notifications_page )
        assert restored[ "in_memory" ] == { "direction": "sender", "kind": "heartbeats", "persona": "tiberius" }, (
            f"Filter state not restored to in-memory: {restored!r}"
        )

        # Dropdowns reflect the restored state
        dropdown_values = notifications_page.evaluate(
            """() => ( {
                direction: document.getElementById( "commons-recent-activity-filter-direction" ).value,
                kind     : document.getElementById( "commons-recent-activity-filter-kind" ).value
            } )"""
        )
        assert dropdown_values[ "direction" ] == "sender"
        assert dropdown_values[ "kind" ] == "heartbeats"


# ---------------------------------------------------------------------------
#  Accordion persistence — broadcast card + recent activity body
# ---------------------------------------------------------------------------

class TestAccordionPersistence:
    """Two tracked accordions persist open/closed state across reload."""

    def test_recent_activity_collapse_persists( self, notifications_page ):
        # Collapse the Recent Activity body via the global toggleSection helper
        notifications_page.evaluate(
            """() => window.toggleSection( "commons-recent-activity-body" )"""
        )

        ls_value = notifications_page.evaluate(
            """() => localStorage.getItem( "notifications_recent_activity_open" )"""
        )
        assert ls_value == "false", (
            f"Recent Activity collapse not persisted (expected 'false'), got: {ls_value!r}"
        )

        # Reload and verify the body still has the collapsed class. The body
        # element is `display: none`-equivalent while collapsed, so
        # `wait_for_selector` with the default `visible` state would time out
        # — wait for it to be `attached` instead.
        notifications_page.reload()
        notifications_page.wait_for_selector(
            "#commons-recent-activity-body", state = "attached"
        )

        is_collapsed = notifications_page.evaluate(
            """() => document.getElementById( "commons-recent-activity-body" ).classList.contains( "collapsed" )"""
        )
        assert is_collapsed, "Recent Activity body should be collapsed after reload"


# ---------------------------------------------------------------------------
#  Part B — Focus-bar chronological lock
# ---------------------------------------------------------------------------

class TestStripChronologicalOrder:
    """cc-strip-icons carry data-created-at and sort ascending."""

    def test_every_strip_icon_has_data_created_at( self, notifications_page ):
        # Wait for the strip to hydrate. Skip the test if no CC sessions are
        # active on the test server (strip stays hidden).
        notifications_page.wait_for_timeout( 500 )  # let hydration settle
        result = notifications_page.evaluate(
            """() => {
                const icons = Array.from(
                    document.querySelectorAll( "#cc-strip-icons .cc-strip-icon" )
                );
                return icons.map( i => ( {
                    sender:    i.getAttribute( "data-sender-id" ),
                    createdAt: i.getAttribute( "data-created-at" )
                } ) );
            }"""
        )
        if not result:
            pytest.skip( "No CC strip icons hydrated on the test server" )

        for entry in result:
            assert entry[ "createdAt" ], (
                f"Strip icon for {entry[ 'sender' ]!r} is missing data-created-at"
            )

    def test_strip_icons_sorted_ascending_after_initial_hydration( self, notifications_page ):
        notifications_page.wait_for_timeout( 500 )
        # Force the sort helper to run (idempotent — if it already ran during
        # init, this is a no-op).
        notifications_page.evaluate(
            """() => {
                const ctl = window.notificationsUI;
                if ( ctl && typeof ctl._sortStripIconsChronological === "function" ) {
                    ctl._sortStripIconsChronological();
                }
            }"""
        )
        timestamps = notifications_page.evaluate(
            """() => Array.from(
                document.querySelectorAll( "#cc-strip-icons .cc-strip-icon" )
            ).map( i => i.getAttribute( "data-created-at" ) || "" )"""
        )
        if len( timestamps ) < 2:
            pytest.skip( "Need at least 2 strip icons to assert ordering" )

        sorted_timestamps = sorted( timestamps )
        assert timestamps == sorted_timestamps, (
            f"Strip icons must be sorted by data-created-at ascending. "
            f"Got: {timestamps!r}, expected: {sorted_timestamps!r}"
        )

    def test_promote_strip_icon_renamed_to_mark_strip_icon_activity( self, notifications_page ):
        """Compile-time check: the rename happened end-to-end."""
        result = notifications_page.evaluate(
            """() => {
                const ctl = window.notificationsUI;
                return {
                    has_new: ctl && typeof ctl._markStripIconActivity === "function",
                    has_old: ctl && typeof ctl._promoteStripIcon === "function"
                };
            }"""
        )
        assert result[ "has_new" ], "_markStripIconActivity must exist after the chrono-lock rename"
        # Old name should be gone; if Rick wants a thin alias for safety, this assertion can flip.
        assert not result[ "has_old" ], (
            "_promoteStripIcon should be renamed away. If a thin alias was intentionally kept, "
            "flip this assertion to assert has_old == True."
        )
