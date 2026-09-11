#!/usr/bin/env python3
"""
E2E — the multiplexer jobs pane's Mine / Not Mine / All Users filter (row 83c3ff74).

Rick's ruling (2026-09-10 ~17:40 EDT): for an admin the jobs pane shows legacy's filter badge
and switch, defaults to OWN jobs, and shares ONE mode with the notifications header. Merged as
47f0a623. test_filter_toggle.py drives only the classic page, so before this file nothing
exercised the multiplexer half end to end.

What is asserted is the REQUEST the browser sends to /api/job-history, not only the DOM: the
badge can read "Not Mine" while the pane asks for everyone's jobs, and only the query string
tells those apart.

| mode        | admin sends                 | non-admin sends |
|-------------|-----------------------------|-----------------|
| Mine        | user_filter=<the admin sub> | no user_filter  |
| Not Mine    | user_filter=!self           | (no switch)     |
| All Users   | user_filter=*               | (no switch)     |

Every click must cause EXACTLY ONE history reload. The count is taken over a quiet window after
the reload's response, so a second reload that lands a moment later is still counted.

Venue: :8000 (monopolize, scheduled) — the admin_page and logged_in_page fixtures wipe
lupin_db_test. Run:
    LUPIN_ROOT=<tree> ./src/scripts/run-e2e-ui-tests.sh -k multiplexer_jobs_filter_mode
"""

from urllib.parse import parse_qs, urlparse

from .conftest import BASE_URL, get_user_id_from_page

MULTIPLEXER_URL = f"{BASE_URL}/app/multiplexer"
HISTORY_PATH    = "/api/job-history"

# Long enough for a doubled reload (a second store event, a second subscriber) to show up.
QUIET_WINDOW_MS = 2000

JOBS_BADGE     = '[data-testid="queues-filter-badge"]'
JOBS_SWITCH    = '[data-testid="multiplexer-jobs-filter-switch"]'
NOTIF_BADGE    = '[data-testid="multiplexer-notifications-filter-badge"]'
JOBS_TOOLBAR   = '#section-toolbar .toolbar-btn[data-section="jobs-pane"]'


def _is_history( url ):
    return urlparse( url ).path == HISTORY_PATH


def _user_filters( history_urls ):
    """
    The decoded user_filter of each captured request, None where the request carried none.

    Ensures:
        - one entry per url, in order
        - "!self" comes back decoded even though the browser sends it as %21self
    """
    filters = []
    for url in history_urls:
        values = parse_qs( urlparse( url ).query ).get( "user_filter" )
        filters.append( None if values is None else values[ 0 ] )
    return filters


def _open_multiplexer( page ):
    """
    Capture every /api/job-history request, load the multiplexer, reveal the jobs pane.

    Requires:
        - page carries a signed-in session (admin_page or logged_in_page)

    Ensures:
        - returns the live list of captured history request urls
        - the boot hydration's response has arrived and the quiet window has passed
        - the cold-hidden jobs pane is visible
    """
    history_urls = []
    page.on( "request", lambda req: history_urls.append( req.url ) if _is_history( req.url ) else None )

    with page.expect_response( lambda r: _is_history( r.url ), timeout=15000 ) as boot_response:
        page.goto( MULTIPLEXER_URL )
    assert boot_response.value.status == 200, f"boot history load answered {boot_response.value.status}"

    page.wait_for_function(
        "() => window.__multiplexerTestHook !== undefined && window.__multiplexerTestHook.eventBus !== undefined",
        timeout=15000,
    )
    page.wait_for_timeout( QUIET_WINDOW_MS )

    page.locator( JOBS_TOOLBAR ).click()
    page.wait_for_selector( '[data-testid="multiplexer-jobs-pane"]', state="visible", timeout=10000 )
    return history_urls


def _click_and_capture_one_reload( page, history_urls, selector ):
    """
    Click a switch button and return the user_filter of the ONE reload it causes.

    Ensures:
        - the reload answered 200
        - exactly one new /api/job-history request was sent, counted after a quiet window
    """
    before = len( history_urls )
    with page.expect_response( lambda r: _is_history( r.url ), timeout=10000 ) as reload_response:
        page.locator( selector ).click()
    assert reload_response.value.status == 200, (
        f"reload after {selector} answered {reload_response.value.status}: {reload_response.value.url}"
    )
    page.wait_for_timeout( QUIET_WINDOW_MS )

    new_filters = _user_filters( history_urls[ before: ] )
    assert len( new_filters ) == 1, (
        f"clicking {selector} sent {len( new_filters )} /api/job-history requests, expected exactly one: "
        f"{history_urls[ before: ]}"
    )
    return new_filters[ 0 ]


def _assert_badge( page, selector, text, mode ):
    badge = page.locator( selector )
    assert badge.is_visible(), f"{selector} is not visible"
    assert badge.text_content() == text, f"{selector} reads {badge.text_content()!r}, expected {text!r}"
    assert badge.get_attribute( "data-mode" ) == mode, (
        f"{selector} data-mode is {badge.get_attribute( 'data-mode' )!r}, expected {mode!r}"
    )


def test_an_admin_boots_in_mine_and_asks_for_their_own_uid( admin_page ):
    """
    Ensures:
        - the jobs badge and switch are visible to an admin, the badge reading 👤 Mine
        - the boot sends ONE history request, and it names the admin's JWT sub
    """
    page         = admin_page
    history_urls = _open_multiplexer( page )
    admin_uid    = get_user_id_from_page( page )

    assert page.locator( JOBS_SWITCH ).is_visible(), "the jobs filter switch is hidden from an admin"
    _assert_badge( page, JOBS_BADGE, "👤 Mine", "own" )
    assert _user_filters( history_urls ) == [ admin_uid ], (
        f"boot history requests {history_urls} — expected exactly one, with user_filter={admin_uid}"
    )


def test_not_mine_sends_one_reload_for_everyone_but_the_admin( admin_page ):
    """
    Ensures:
        - clicking the jobs switch's Not Mine sends exactly one reload with user_filter=!self
        - the jobs badge reads 🚫 Not Mine, and the notifications badge follows (one shared mode)
    """
    page         = admin_page
    history_urls = _open_multiplexer( page )

    user_filter = _click_and_capture_one_reload(
        page, history_urls, '[data-testid="multiplexer-jobs-filter-others-btn"]'
    )

    assert user_filter == "!self", f"Not Mine sent user_filter={user_filter!r}, expected '!self'"
    _assert_badge( page, JOBS_BADGE, "🚫 Not Mine", "others" )
    assert page.locator( NOTIF_BADGE ).text_content() == "🚫 Not Mine", (
        f"the notifications badge did not follow the jobs switch: {page.locator( NOTIF_BADGE ).text_content()!r}"
    )


def test_all_users_sends_one_reload_for_every_user( admin_page ):
    """
    Ensures:
        - clicking the jobs switch's All Users sends exactly one reload with user_filter=*
        - the jobs badge reads 👥 All Users
    """
    page         = admin_page
    history_urls = _open_multiplexer( page )

    user_filter = _click_and_capture_one_reload(
        page, history_urls, '[data-testid="multiplexer-jobs-filter-all-btn"]'
    )

    assert user_filter == "*", f"All Users sent user_filter={user_filter!r}, expected '*'"
    _assert_badge( page, JOBS_BADGE, "👥 All Users", "all" )


def test_back_to_mine_names_the_admin_uid_again( admin_page ):
    """
    Ensures:
        - after All Users, clicking Mine sends exactly one reload naming the admin's sub — not
          a bare request, which /api/job-history answers for an admin with EVERY user's jobs
    """
    page         = admin_page
    history_urls = _open_multiplexer( page )
    admin_uid    = get_user_id_from_page( page )

    _click_and_capture_one_reload( page, history_urls, '[data-testid="multiplexer-jobs-filter-all-btn"]' )
    user_filter = _click_and_capture_one_reload(
        page, history_urls, '[data-testid="multiplexer-jobs-filter-own-btn"]'
    )

    assert user_filter == admin_uid, f"Mine sent user_filter={user_filter!r}, expected the admin sub {admin_uid!r}"
    _assert_badge( page, JOBS_BADGE, "👤 Mine", "own" )


def test_the_jobs_badge_follows_the_notifications_header_switch( admin_page ):
    """
    Ensures:
        - a mode change made from the NOTIFICATIONS header's switch reloads the jobs history
          exactly once, with user_filter=!self
        - the jobs badge reads 🚫 Not Mine without the jobs switch being touched
    """
    page         = admin_page
    history_urls = _open_multiplexer( page )

    user_filter = _click_and_capture_one_reload(
        page, history_urls, '[data-testid="multiplexer-notifications-filter-others-btn"]'
    )

    assert user_filter == "!self", (
        f"Not Mine from the notifications header sent user_filter={user_filter!r}, expected '!self'"
    )
    _assert_badge( page, JOBS_BADGE, "🚫 Not Mine", "others" )


def test_a_non_admin_sees_no_switch_and_sends_no_user_filter( logged_in_page ):
    """
    Ensures:
        - the jobs badge and switch are hidden from a regular user
        - the boot's history request carries no user_filter (the server scopes them itself)
    """
    page         = logged_in_page
    history_urls = _open_multiplexer( page )

    assert not page.locator( JOBS_SWITCH ).is_visible(), "a regular user can see the jobs filter switch"
    assert not page.locator( JOBS_BADGE ).is_visible(), "a regular user can see the jobs filter badge"
    assert _user_filters( history_urls ) == [ None ], (
        f"a regular user's boot history requests {history_urls} — expected exactly one, with no user_filter"
    )
