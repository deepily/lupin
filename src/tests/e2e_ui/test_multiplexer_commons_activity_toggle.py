#!/usr/bin/env python3
"""
E2E — Multiplexer Lane D WP3/WP11: commons "Recent Activity" Show-more toggle (F4).

Exercises CommonsStore + CommonsActivityRenderer's overflow toggle end-to-end
against a stubbed `/api/commons/broadcast-history`: a body that overflows the
2-line clamp reveals its `.commons-activity-entry-body-toggle`, a short body
keeps it hidden, clicking flips the `expanded` class + the "Show more ▾" /
"Show less ▴" label, and — the F4 fix proper — entries rendered while the
panel body is COLLAPSED (zero clientHeight, unmeasurable) get their toggle
revealed by the ResizeObserver re-measure when the panel expands.

Assertions anchor on the toggle's `hidden` property, the content element's
class list, and the toggle's text — per row, located by persona name — not
bare element presence.

Venue: :8000 (monopolize, scheduled) — `test_multiplexer_*` E2E batch. Per
CLAUDE.local.md "USER IS NEVER A TESTER": every assertion is AI.

Usage:
    pytest src/tests/e2e_ui/test_multiplexer_commons_activity_toggle.py -v
    LUPIN_API_URL=http://localhost:8000 pytest src/tests/e2e_ui/test_multiplexer_commons_activity_toggle.py -v
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import pytest
import requests

BASE_URL        = os.environ.get( "LUPIN_API_URL", "http://localhost:7999" )
MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"

HISTORY_ROUTE = "**/api/commons/broadcast-history*"
POOL_ROUTE    = "**/api/cosa-voice/voice-persona/pool"

LONG_PERSONA  = "Verbosa"
SHORT_PERSONA = "Terse"

# Comfortably past the 2-line CSS clamp regardless of panel width.
LONG_BODY  = "\n\n".join( f"Paragraph { i }: " + "lorem ipsum dolor sit amet " * 6 for i in range( 6 ) )
SHORT_BODY = "ok"


def _get_credentials() -> tuple[ str, str ]:
    email    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
    password = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )
    if not email or not password:
        pytest.skip( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL / _PASSWORD env vars not set" )
    return email, password


def _login_tokens() -> tuple[ str, str ]:
    email, password = _get_credentials()
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": email, "password": password },
        timeout = 10,
    )
    assert resp.status_code == 200, f"login failed: { resp.status_code } { resp.text }"
    tokens = resp.json()[ "tokens" ]
    return tokens[ "access_token" ], tokens[ "refresh_token" ]


def _history_entries() -> list[ dict ]:
    now_iso = datetime.now( timezone.utc ).isoformat()
    return [
        {
            "ts"           : now_iso,
            "topic"        : "broadcast",
            "topic_kind"   : "reserved",
            "persona_name" : LONG_PERSONA,
            "persona_icon" : "📣",
            "body"         : LONG_BODY,
        },
        {
            "ts"           : now_iso,
            "topic"        : "broadcast",
            "topic_kind"   : "reserved",
            "persona_name" : SHORT_PERSONA,
            "persona_icon" : "🤐",
            "body"         : SHORT_BODY,
        },
    ]


def _open( page ):
    """Seed auth, stub broadcast-history (long + short entry) and the persona
    pool, navigate, wait for the test hook + the two rendered rows."""
    access, refresh = _login_tokens()
    page.context.add_init_script(
        f"window.localStorage.setItem('lupin_access_token', { json.dumps( access ) });"
        f"window.localStorage.setItem('lupin_refresh_token', { json.dumps( refresh ) });"
    )

    page.route( HISTORY_ROUTE, lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps( { "entries": _history_entries() } ),
    ) )
    page.route( POOL_ROUTE, lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps( { "pool": [], "active_sessions": [] } ),
    ) )

    page.goto( MULTIPLEXER_URL, wait_until="networkidle", timeout=15_000 )
    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=10_000,
    )
    page.wait_for_function(
        "() => document.querySelectorAll( '#commons-activity-entries .commons-activity-entry' ).length === 2",
        timeout=5_000,
    )


def _row( page, persona: str ):
    return page.locator( "#commons-activity-entries .commons-activity-entry" ).filter(
        has=page.locator( f'.commons-activity-entry-name[title="{persona}"]' )
    )


def _toggle_state( page, persona: str ) -> dict:
    return page.evaluate(
        """( persona ) => {
            const rows = Array.from( document.querySelectorAll( '#commons-activity-entries .commons-activity-entry' ) );
            const row  = rows.find( r => {
                const name = r.querySelector( '.commons-activity-entry-name' );
                return name && name.getAttribute( 'title' ) === persona;
            } );
            if ( !row ) return null;
            const toggle  = row.querySelector( '.commons-activity-entry-body-toggle' );
            const content = row.querySelector( '.commons-activity-entry-body-content' );
            return {
                toggle_hidden : toggle ? toggle.hidden : null,
                toggle_text   : toggle ? toggle.textContent : null,
                expanded      : content ? content.classList.contains( 'expanded' ) : null,
            };
        }""",
        persona,
    )


def test_overflowing_body_reveals_toggle_short_body_does_not( page ):
    """
    Ensures:
        - The entry whose body overflows the 2-line clamp gets its Show-more
          toggle revealed by the layout measure (hidden flips false)
        - The short entry's toggle STAYS hidden — reveal is overflow-driven,
          not unconditional
    """
    _open( page )

    page.wait_for_function(
        """( persona ) => {
            const rows = Array.from( document.querySelectorAll( '#commons-activity-entries .commons-activity-entry' ) );
            const row  = rows.find( r => r.querySelector( `.commons-activity-entry-name[title="${persona}"]` ) );
            const t    = row && row.querySelector( '.commons-activity-entry-body-toggle' );
            return t && t.hidden === false;
        }""",
        arg=LONG_PERSONA,
        timeout=5_000,
    )

    long_state  = _toggle_state( page, LONG_PERSONA )
    short_state = _toggle_state( page, SHORT_PERSONA )
    assert long_state[ "toggle_hidden" ]  is False
    assert long_state[ "toggle_text" ]    == "Show more ▾"
    assert long_state[ "expanded" ]       is False
    assert short_state[ "toggle_hidden" ] is True, \
        "a body inside the clamp must never grow a Show-more toggle"


def test_toggle_click_expands_and_second_click_collapses( page ):
    """
    Ensures:
        - Clicking the revealed toggle adds `expanded` to the body content and
          relabels to "Show less ▴"; a second click reverts both — the
          delegated-listener round-trip (store-action + delegation idiom,
          no inline onclick)
    """
    _open( page )
    page.wait_for_function(
        """( persona ) => {
            const rows = Array.from( document.querySelectorAll( '#commons-activity-entries .commons-activity-entry' ) );
            const row  = rows.find( r => r.querySelector( `.commons-activity-entry-name[title="${persona}"]` ) );
            const t    = row && row.querySelector( '.commons-activity-entry-body-toggle' );
            return t && t.hidden === false;
        }""",
        arg=LONG_PERSONA,
        timeout=5_000,
    )

    _row( page, LONG_PERSONA ).locator( ".commons-activity-entry-body-toggle" ).click()
    state = _toggle_state( page, LONG_PERSONA )
    assert state[ "expanded" ]    is True
    assert state[ "toggle_text" ] == "Show less ▴"

    _row( page, LONG_PERSONA ).locator( ".commons-activity-entry-body-toggle" ).click()
    state = _toggle_state( page, LONG_PERSONA )
    assert state[ "expanded" ]    is False
    assert state[ "toggle_text" ] == "Show more ▾"


def test_entries_rendered_while_collapsed_reveal_toggle_on_expand( page ):
    """
    Ensures:
        - The F4 fix proper: rows re-rendered while the panel body is
          collapsed (clientHeight 0 — unmeasurable) register a ResizeObserver
          and reveal the toggle when the panel expands and layout returns
    """
    _open( page )
    page.wait_for_function(
        """( persona ) => {
            const rows = Array.from( document.querySelectorAll( '#commons-activity-entries .commons-activity-entry' ) );
            const row  = rows.find( r => r.querySelector( `.commons-activity-entry-name[title="${persona}"]` ) );
            const t    = row && row.querySelector( '.commons-activity-entry-body-toggle' );
            return t && t.hidden === false;
        }""",
        arg=LONG_PERSONA,
        timeout=5_000,
    )

    # Collapse the panel, then force a full re-render (refresh re-hydrates from
    # the stub) — the fresh rows are born unmeasurable. Click the header TITLE:
    # the delegation deliberately ignores clicks originating inside
    # .commons-activity-controls, which covers the header's center point.
    page.locator( "#commons-activity-header h5" ).click()
    # state="attached": the collapsed body is display:none — the default
    # "visible" wait would spin forever on an element that is correctly hidden.
    page.wait_for_selector( "#commons-activity-body.collapsed", state="attached", timeout=2_000 )

    # Mark the pre-refresh rows so the wait below detects ACTUAL replacement —
    # waiting on row COUNT alone is vacuously true before the re-render lands
    # (the race that false-passed this test's first draft).
    page.evaluate(
        """() => document.querySelectorAll( '#commons-activity-entries .commons-activity-entry' )
                    .forEach( r => r.setAttribute( 'data-e2e-stale-row', '1' ) )"""
    )
    page.locator( "#commons-activity-refresh" ).click()
    page.wait_for_function(
        """() => {
            const rows = document.querySelectorAll( '#commons-activity-entries .commons-activity-entry' );
            return rows.length === 2
                && Array.from( rows ).every( r => !r.hasAttribute( 'data-e2e-stale-row' ) );
        }""",
        timeout=5_000,
    )
    # Let the measure rafFn tick run before asserting it (correctly) bailed.
    page.wait_for_timeout( 300 )
    collapsed_state = _toggle_state( page, LONG_PERSONA )
    assert collapsed_state[ "toggle_hidden" ] is True, \
        "while collapsed the fresh row cannot be measured — toggle must still be hidden"

    # Expand → ResizeObserver fires on the now-laid-out content → toggle reveals.
    page.locator( "#commons-activity-header h5" ).click()
    page.wait_for_function(
        """( persona ) => {
            const rows = Array.from( document.querySelectorAll( '#commons-activity-entries .commons-activity-entry' ) );
            const row  = rows.find( r => r.querySelector( `.commons-activity-entry-name[title="${persona}"]` ) );
            const t    = row && row.querySelector( '.commons-activity-entry-body-toggle' );
            return t && t.hidden === false;
        }""",
        arg=LONG_PERSONA,
        timeout=5_000,
    )
    short_state = _toggle_state( page, SHORT_PERSONA )
    assert short_state[ "toggle_hidden" ] is True, \
        "the RO re-measure must stay overflow-driven — short bodies keep no toggle"
