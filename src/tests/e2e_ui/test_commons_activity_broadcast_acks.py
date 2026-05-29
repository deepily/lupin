"""
Playwright E2E for the broadcast-acks body-phrasing transform in
`_renderCommonsEntry` (notifications.js).

Per Rick's 2026-05-17 voice direction: rows with `topic === "broadcast-acks"`
render the bare `body` status word ("completed" / "skipped" /
"rejected-malformed") as a more descriptive phrase ("received broadcast" /
"skipped broadcast" / "rejected broadcast (malformed)") so the Recent
Activity stream reads as events rather than status codes. Unknown status
words pass through verbatim (defensive — the writer contract in
`broadcast_handler.py:_post_ack` is untouched).

**Venue: :8000 (monopolize)**. Submit via:

    POST /api/test-suite/submit
    {
        "test_types"  : "e2e",
        "pytest_args" : "-k test_commons_activity_broadcast_acks",
        "auto_fix_on_failure": false
    }

**Test approach**: pure DOM render test using `page.evaluate()` to invoke
`_renderCommonsEntry` directly with a synthetic broadcast-ack entry, then
assert the rendered body text content.
"""

import pytest


@pytest.mark.e2e
class TestBroadcastAcksPhrasingTransform:

    @pytest.mark.parametrize(
        ( "status_body", "expected_phrase" ),
        [
            ( "completed",          "received broadcast" ),
            ( "skipped",            "skipped broadcast" ),
            ( "rejected-malformed", "rejected broadcast (malformed)" ),
        ],
    )
    def test_known_ack_status_renders_as_descriptive_phrase(
        self, notifications_page, status_body, expected_phrase
    ):
        """
        Each of the three known broadcast-ack statuses is rewritten to its
        descriptive phrase when topic === "broadcast-acks".
        """
        page = notifications_page

        section = page.locator( "#commons-recent-activity-section" )
        assert section.count() >= 1, "Recent Activity section missing — is commons_traffic_visibility_enabled?"

        page.evaluate(
            """({ statusBody, testid }) => {
                const entry = {
                    body              : statusBody,
                    persona_name      : "tiberius",
                    persona_icon      : "🌑",
                    persona_color     : "#495057",
                    topic             : "broadcast-acks",
                    topic_kind        : "reserved",
                    ts                : new Date().toISOString(),
                    metadata          : { kind: "ack", broadcast_id: "test-bc", status: statusBody },
                };
                const row = window.notificationsUI._renderCommonsEntry( entry );
                row.setAttribute( "data-testid", testid );
                const entriesEl = document.getElementById( "commons-recent-activity-entries" );
                if ( entriesEl ) entriesEl.appendChild( row );
                const body = document.getElementById( "commons-recent-activity-body" );
                if ( body && body.classList.contains( "collapsed" ) ) {
                    body.classList.remove( "collapsed" );
                }
            }""",
            { "statusBody": status_body, "testid": f"ack-row-{status_body}" }
        )

        row = page.locator( f'[data-testid="ack-row-{status_body}"]' )
        row.wait_for( state="attached", timeout=5000 )

        content = row.locator( ".commons-activity-entry-body-content" ).first
        content_text = content.inner_text().strip()
        assert content_text == expected_phrase, (
            f"broadcast-ack body for status={status_body!r} should render "
            f"as {expected_phrase!r}, got {content_text!r}"
        )

    def test_unknown_ack_status_passes_through_verbatim( self, notifications_page ):
        """
        Defensive passthrough — an unmapped status word renders as-is so a
        future writer-side status addition does not silently swallow into "".
        """
        page = notifications_page

        page.evaluate(
            """() => {
                const entry = {
                    body              : "queued-for-retry",
                    persona_name      : "rio",
                    persona_icon      : "⚡",
                    persona_color     : "#1c4587",
                    topic             : "broadcast-acks",
                    topic_kind        : "reserved",
                    ts                : new Date().toISOString(),
                    metadata          : { kind: "ack", broadcast_id: "test-bc-2", status: "queued-for-retry" },
                };
                const row = window.notificationsUI._renderCommonsEntry( entry );
                row.setAttribute( "data-testid", "ack-row-unknown" );
                const entriesEl = document.getElementById( "commons-recent-activity-entries" );
                if ( entriesEl ) entriesEl.appendChild( row );
            }"""
        )

        row = page.locator( '[data-testid="ack-row-unknown"]' )
        row.wait_for( state="attached", timeout=5000 )

        content = row.locator( ".commons-activity-entry-body-content" ).first
        content_text = content.inner_text().strip()
        assert content_text == "queued-for-retry", (
            f"Unknown ack status should pass through verbatim, got {content_text!r}"
        )

    def test_non_broadcast_acks_topic_does_not_get_transform( self, notifications_page ):
        """
        The transform must be scoped to `topic === "broadcast-acks"`. Entries
        on other topics whose body happens to be the word "completed" render
        verbatim.
        """
        page = notifications_page

        page.evaluate(
            """() => {
                const entry = {
                    body              : "completed",
                    persona_name      : "maria",
                    persona_icon      : "🌸",
                    persona_color     : "#F06292",
                    topic             : "coordination",
                    topic_kind        : "free-form",
                    ts                : new Date().toISOString(),
                    metadata          : { },
                };
                const row = window.notificationsUI._renderCommonsEntry( entry );
                row.setAttribute( "data-testid", "free-form-completed-row" );
                const entriesEl = document.getElementById( "commons-recent-activity-entries" );
                if ( entriesEl ) entriesEl.appendChild( row );
            }"""
        )

        row = page.locator( '[data-testid="free-form-completed-row"]' )
        row.wait_for( state="attached", timeout=5000 )

        content = row.locator( ".commons-activity-entry-body-content" ).first
        content_text = content.inner_text().strip()
        assert content_text == "completed", (
            f"Free-form topic with body=completed should render verbatim, got {content_text!r}"
        )
