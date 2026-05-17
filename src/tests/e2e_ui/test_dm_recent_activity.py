"""
Playwright E2E for Inter-Session DM topic-chip render + visual baseline.

Updated 2026-05-17 (Rick voice request): collapsed the older
`dm-tiberius → @Tiberius` two-element render into a single
`@tiberius` topic chip. The `.commons-activity-dm-badge` pill is gone;
the chip itself now carries the `@<persona>` form for `dm-*` topics.

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
verifies ONLY the render path: a `dm-<persona>` topic renders as a
single `@<persona>` chip, and no `.commons-activity-dm-badge` element
exists anywhere on the page.
"""

import pytest


@pytest.mark.e2e
class TestDmRecentActivityChip:

    def test_dm_topic_renders_as_at_persona_chip( self, notifications_page ):
        """
        Given an entry whose topic is `dm-<persona>`, _renderCommonsEntry
        emits a single `.commons-activity-entry-topic-chip` whose text is
        `@<persona>` — and NO `.commons-activity-dm-badge` (retired).
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
                row.setAttribute( "data-testid", "dm-chip-row" );
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

        dm_row = page.locator( '[data-testid="dm-chip-row"]' )
        dm_row.wait_for( state="attached", timeout=5000 )

        # The topic chip must render as `@radio` (NOT `dm-radio`)
        chip = dm_row.locator( ".commons-activity-entry-topic-chip" ).first
        chip.wait_for( state="attached", timeout=5000 )
        assert chip.is_visible(), "Topic chip element exists but is not visible"
        chip_text = chip.inner_text().strip()
        assert chip_text == "@radio", f"Topic chip text mismatch: {chip_text!r} (expected '@radio')"

        # The legacy DM badge must NOT exist anywhere on the page
        badge_count = page.locator( ".commons-activity-dm-badge" ).count()
        assert badge_count == 0, f".commons-activity-dm-badge should be retired, found {badge_count}"

    def test_non_dm_topic_keeps_literal_chip( self, notifications_page ):
        """
        Free-form non-DM topics (e.g., `coordination`, `help-wanted`) render
        the topic name verbatim — no `@` prefix transform. Reserved topics
        (`broadcasts`, `presence`, `system-events`) stay hidden via
        `topic_kind === "reserved"`.
        """
        page = notifications_page

        # Inject a non-DM free-form entry
        page.evaluate(
            """() => {
                const entry = {
                    body              : "Plain coordination post — no DM transform expected.",
                    persona_name      : "plain-broadcast",
                    persona_icon      : "📣",
                    persona_color     : "#6c757d",
                    topic             : "coordination",
                    ts                : new Date().toISOString(),
                    metadata          : { kind: "broadcast" },
                };
                const row = window.notificationsUI._renderCommonsEntry( entry );
                row.setAttribute( "data-testid", "plain-non-dm-row" );
                const entriesEl = document.getElementById( "commons-recent-activity-entries" );
                entriesEl.appendChild( row );
            }"""
        )

        plain_row = page.locator( '[data-testid="plain-non-dm-row"]' )
        plain_row.wait_for( state="attached", timeout=5000 )

        chip = plain_row.locator( ".commons-activity-entry-topic-chip" ).first
        chip_text = chip.inner_text().strip()
        assert chip_text == "coordination", f"Non-DM chip should render verbatim, got {chip_text!r}"
        assert not chip_text.startswith( "@" ), f"Non-DM chip should NOT carry @ prefix, got {chip_text!r}"


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
