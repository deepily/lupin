"""
AC9e + AC9f Playwright E2E for Inter-Session DM badge render + visual baseline.

Per `src/rnd/v0.1.7/2026.05.15-inter-session-direct-messaging-design.md` AC9e + AC9f.

**Venue: :8000 (monopolize)**. Submit via:

    POST /api/test-suite/submit
    {
        "test_types"        : "e2e",
        "pytest_args"       : "-k test_dm_recent_activity",
        "scheduled_at"      : "<user-confirmed-slot>",
        "auto_fix_on_failure": false
    }

For visual baseline capture, add `--update-snapshots` to pytest_args (per
`feedback_baseline_capture_disable_tfe` — `auto_fix_on_failure: False` is
critical so TFE doesn't intercept the library-convention "Snapshots updated"
exit and try to "fix" a non-bug).

**Test approach**: pure DOM render test using `page.evaluate()` to invoke
`_renderCommonsEntry` directly with a synthetic DM entry. No backend
round-trip — that's covered by the integration test in
`src/tests/integration/test_dm_integration_live.py`. The E2E UI test
verifies ONLY the render path: given an entry with
`metadata.recipient_persona` set, the `.commons-activity-dm-badge` pill
appears in the DOM with the right text content.
"""

import pytest


@pytest.mark.e2e
class TestDmRecentActivityBadge:

    def test_dm_badge_renders_for_entries_with_recipient_persona( self, notifications_page ):
        """
        Given an entry with metadata.recipient_persona, _renderCommonsEntry
        appends a `.commons-activity-dm-badge` pill containing "→ @<persona>".
        """
        page = notifications_page

        # Ensure Recent Activity section is present (rendered for feature-enabled config)
        section = page.locator( "#commons-recent-activity-section" )
        assert section.count() >= 1, "Recent Activity section missing — is commons_traffic_visibility_enabled?"

        # Inject a synthetic DM entry via the render function
        result = page.evaluate(
            """() => {
                const entry = {
                    body              : "Test DM body — do you have the latest commit hash for X?",
                    persona_name      : "tester-asker",
                    persona_icon      : "🧪",
                    persona_color     : "#1c4587",
                    topic             : "dm-radio",
                    ts                : new Date().toISOString(),
                    metadata          : { recipient_persona: "radio", kind: "question" },
                };
                const row = window.notificationsUI._renderCommonsEntry( entry );
                const entriesEl = document.getElementById( "commons-recent-activity-entries" );
                if ( !entriesEl ) return { ok: false, reason: "entries container missing" };
                // Prepend so it's visible at top
                if ( entriesEl.firstChild ) {
                    entriesEl.insertBefore( row, entriesEl.firstChild );
                } else {
                    entriesEl.appendChild( row );
                }
                // Make sure the section body is expanded so the row is visible
                const body = document.getElementById( "commons-recent-activity-body" );
                if ( body && body.classList.contains( "collapsed" ) ) {
                    body.classList.remove( "collapsed" );
                }
                return { ok: true };
            }"""
        )
        assert result[ "ok" ], result.get( "reason" )

        # The DM badge must be present + carry the expected text
        badge = page.locator( ".commons-activity-dm-badge" ).first
        badge.wait_for( state="attached", timeout=5000 )
        assert badge.is_visible(), "DM badge element exists but is not visible"
        assert "→ @radio" in badge.inner_text(), f"Badge text mismatch: {badge.inner_text()!r}"

    def test_dm_badge_omitted_when_no_recipient_persona( self, notifications_page ):
        """
        Non-DM entries (no metadata.recipient_persona) do NOT get a DM badge.
        Preserves the Phase 2 broadcast rendering contract.
        """
        page = notifications_page

        # Inject a non-DM entry
        page.evaluate(
            """() => {
                const entry = {
                    body              : "Plain broadcast body — no recipient metadata.",
                    persona_name      : "plain-broadcast",
                    persona_icon      : "📣",
                    persona_color     : "#6c757d",
                    topic             : "broadcasts",
                    ts                : new Date().toISOString(),
                    metadata          : { kind: "broadcast" },  // no recipient_persona
                };
                const row = window.notificationsUI._renderCommonsEntry( entry );
                row.setAttribute( "data-testid", "plain-non-dm-row" );
                const entriesEl = document.getElementById( "commons-recent-activity-entries" );
                entriesEl.appendChild( row );
            }"""
        )

        plain_row = page.locator( '[data-testid="plain-non-dm-row"]' )
        plain_row.wait_for( state="attached", timeout=5000 )
        # The plain row should NOT contain a DM badge
        badge_count = plain_row.locator( ".commons-activity-dm-badge" ).count()
        assert badge_count == 0, f"Non-DM entry should not have DM badge, found {badge_count}"


@pytest.mark.e2e
@pytest.mark.visual
class TestDmRecentActivityVisualBaseline:

    def test_dm_badge_visual_baseline( self, notifications_page, assert_snapshot ):
        """
        Visual regression baseline for the DM badge pill styling. Captures a
        screenshot of the Recent Activity entry containing a DM badge so future
        runs can detect unintended styling drift.

        First-run protocol (per `feedback_baseline_capture_disable_tfe`):
        submit with `--update-snapshots` AND `auto_fix_on_failure: False`.
        Subsequent runs assert against the captured baseline.
        """
        page = notifications_page

        # Inject a deterministic DM entry
        page.evaluate(
            """() => {
                const entry = {
                    body              : "Visual regression baseline DM entry",
                    persona_name      : "maria",
                    persona_icon      : "🌸",
                    persona_color     : "#F06292",
                    topic             : "dm-radio",
                    ts                : "2026-05-15T12:00:00.000Z",
                    metadata          : { recipient_persona: "radio", kind: "question" },
                };
                // Clear existing entries for deterministic snapshot
                const entriesEl = document.getElementById( "commons-recent-activity-entries" );
                if ( entriesEl ) {
                    entriesEl.innerHTML = "";
                    const row = window.notificationsUI._renderCommonsEntry( entry );
                    row.setAttribute( "data-testid", "visual-baseline-dm-row" );
                    entriesEl.appendChild( row );
                }
                // Ensure section visible
                const body = document.getElementById( "commons-recent-activity-body" );
                if ( body && body.classList.contains( "collapsed" ) ) {
                    body.classList.remove( "collapsed" );
                }
            }"""
        )

        # Wait for the row to settle
        row = page.locator( '[data-testid="visual-baseline-dm-row"]' )
        row.wait_for( state="visible", timeout=5000 )

        # Snapshot ONLY the DM entry row — narrowest deterministic surface
        screenshot = row.screenshot()
        assert_snapshot( screenshot, name="dm-badge-recent-activity" )
