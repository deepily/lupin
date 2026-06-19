"""
E2E UI (Playwright) — read-only Fleet-Status panel in the notifications client.

Design: src/rnd/v0.1.8/2026.06.09-fleet-status-table-notifications-client/01-design.md
  §5 (columns) · §6 (panel + states) · §7 (hierarchy) · §8 (E2E row).
  NOTE: the table is now EIGHT columns — the six §5 columns + the two
  context-pressure columns (% Window + Window) added by 02-context-window-columns.md.
Frontend under test: P2 (held 5f52cfd) — `window.notificationsUI` fleet-status methods.

Strategy: the panel reads `GET /api/arbiter/fleet-state` (P1's enriched composite).
We `page.route()`-stub that endpoint with deterministic composites (the locked §4
contract shape) BEFORE navigation, stop the 60s auto-poll for determinism, and drive
each render via `window.notificationsUI.refreshFleetStatus()`. This keeps the suite
independent of whether a live arbiter is running on :8001.

Asserts (per Tiberius's P3 brief):
  1. #section-fleet-status accordion + the fleet-status-toolbar-btn render.
  2. Grouped table from a seeded composite — managers as group headers, workers
     nested, Unmanaged group LAST (§7).
  3. All eight columns (the six §5 columns + % Window + Window).
  4. READ-ONLY — no mutating controls / no action column; ⟳ only re-fetches.
  5. The §6.4 states: unreachable/null → offline banner; empty → "No active
     sessions"; populated → table.
  6. Visual snapshot of the populated panel (container only — excludes the live
     last-updated stamp so the baseline stays deterministic).

Venue: :8000 (scheduled monopolize-mode via /api/test-suite/submit). Do NOT run
ad-hoc against :7999. Visual baseline first-run: submit with `--update-snapshots`
AND `auto_fix_on_failure: False` (per `feedback_baseline_capture_disable_tfe`).
"""

import json

from .conftest import BASE_URL


# ── Locked §4 contract rows (per-session role + manager; liveness with the 4 raw ages) ──

_TIBERIUS = {
    "session_id": "d9e65cd8", "persona": "Tiberius", "state": "working",
    "holding_on": "none", "stuck": False, "role": "manager", "manager": None,
    "liveness": { "bridge_age_s": 4, "event_age_s": 2100, "commons_age_s": None,
                  "idle_prompt_age_s": None, "freshest_age_s": 4, "verdict": "LIVE" },
}
_RIO = {
    "session_id": "110ff47d", "persona": "Rio", "state": "working",
    "holding_on": "none", "stuck": False, "role": "worker", "manager": "Tiberius",
    "liveness": { "bridge_age_s": 10, "event_age_s": 30, "commons_age_s": 5,
                  "idle_prompt_age_s": 60, "freshest_age_s": 5, "verdict": "LIVE" },
}
_RADIO = {
    "session_id": "aa11bb22", "persona": "Mr. Radio", "state": "stuck",
    "holding_on": "peer:Rio", "stuck": True, "role": "worker", "manager": "Tiberius",
    "liveness": { "bridge_age_s": 720, "event_age_s": 720, "commons_age_s": 720,
                  "idle_prompt_age_s": 720, "freshest_age_s": 720, "verdict": "stale 12m" },
}
_MARIA = {
    "session_id": "cc33dd44", "persona": "María", "state": "idle",
    "holding_on": "none", "stuck": False, "role": "worker", "manager": None,
    "liveness": { "bridge_age_s": 360, "event_age_s": 360, "commons_age_s": 360,
                  "idle_prompt_age_s": 360, "freshest_age_s": 360, "verdict": "quiet 6m" },
}

_POPULATED_SESSIONS = [ _TIBERIUS, _RIO, _RADIO, _MARIA ]


def _composite( sessions, *, app_timezone="America/New_York",
                status="ok", fleet_arbiter=True ):
    """Build a :7999-mirror composite (the shape the panel consumes)."""
    if not fleet_arbiter:
        return { "status": status, "health_watcher": None, "fleet_arbiter": None }
    return {
        "status"         : status,
        "health_watcher" : None,
        "fleet_arbiter"  : {
            "generated_at"  : "2026-06-09T12:00:00-04:00",
            "session_count" : len( sessions ),
            "sessions"      : sessions,
        },
        "app_timezone"   : app_timezone,
    }


def _open_panel( page, composite ):
    """
    Register a stub for /api/arbiter/fleet-state returning `composite`, navigate
    to the notifications page, stop the 60s auto-poll, and render once.

    Returns a mutable `holder` dict ({ "body": <json>, "hits": <int> }); mutate
    holder["body"] then call `_refresh(page)` to drive a state transition. The
    handler bumps holder["hits"] so read-only re-fetch assertions can count GETs.
    """
    holder = { "body": json.dumps( composite ), "hits": 0 }

    def _route( route ):
        holder[ "hits" ] += 1
        route.fulfill( status=200, content_type="application/json", body=holder[ "body" ] )

    page.route( "**/api/arbiter/fleet-state", _route )
    page.goto( f"{BASE_URL}/app/notifications?classic=1" )
    page.wait_for_load_state( "networkidle" )
    # Stop the interval so only our explicit refreshes drive the panel (determinism).
    page.evaluate( "() => window.notificationsUI.stopFleetStatusPolling()" )
    _refresh( page )
    return holder


def _refresh( page ):
    """Drive one fetch→render cycle and let the DOM settle."""
    page.evaluate( "async () => { await window.notificationsUI.refreshFleetStatus(); }" )
    page.wait_for_timeout( 150 )


class TestFleetStatusChrome:
    """AC1 — the accordion + toolbar jump-icon render."""

    def test_section_and_toolbar_button_present( self, logged_in_page ):
        page = logged_in_page
        _open_panel( page, _composite( _POPULATED_SESSIONS ) )

        assert page.locator( "#section-fleet-status" ).count() == 1, "fleet-status accordion present"
        assert page.get_by_test_id( "fleet-status-toolbar-btn" ).count() == 1, "🛰️ toolbar jump-icon present"
        # The jump-icon's data-section wires the section show/hide (same as every toolbar btn).
        assert page.get_by_test_id( "fleet-status-toolbar-btn" ).get_attribute( "data-section" ) == "section-fleet-status"


class TestFleetStatusHierarchy:
    """AC2 + AC3 — grouped table (§7) and the six essentials columns (§5)."""

    def test_grouped_table_managers_workers_unmanaged_last( self, logged_in_page ):
        page = logged_in_page
        _open_panel( page, _composite( _POPULATED_SESSIONS ) )

        container = page.get_by_test_id( "fleet-status-container" )
        assert container.locator( "table.fleet-status-table" ).count() == 1, "grouped table rendered"

        # Group headers: a manager header (Tiberius) and the Unmanaged bucket.
        headers = container.locator( "tr.fleet-group-header" )
        assert headers.count() == 2, "one manager group + one Unmanaged group"
        first_header_text = headers.nth( 0 ).text_content()
        last_header_text  = headers.nth( headers.count() - 1 ).text_content()
        assert "Tiberius" in first_header_text, "manager group header first"
        assert "(Unmanaged)" in last_header_text, "Unmanaged group LAST (§7)"

        # Workers nested under their manager (Rio + Mr. Radio), María in Unmanaged.
        worker_rows = container.locator( "tr.fleet-row-worker" )
        assert worker_rows.count() == 3, "Rio + Mr. Radio + María are worker rows"
        body_text = container.text_content()
        for who in ( "Tiberius", "Rio", "Mr. Radio", "María" ):
            assert who in body_text, f"{who} rendered"

        # Manager row carries the manager class (not a worker).
        assert container.locator( "tr.fleet-row-manager" ).count() == 1

    def test_all_columns_present_and_no_action_column( self, logged_in_page ):
        page = logged_in_page
        _open_panel( page, _composite( _POPULATED_SESSIONS ) )

        headers = page.get_by_test_id( "fleet-status-container" ).locator( "thead th" )
        texts = [ headers.nth( i ).text_content().strip() for i in range( headers.count() ) ]
        # Eight columns, in order: the six §5 columns + the two context-pressure
        # columns added by 02-context-window-columns.md (% Window + Window).
        assert texts == [ "Who", "Role", "State", "Holding on", "Stuck", "Liveness", "% Window", "Window" ], \
            f"exactly the eight columns, in order — got {texts}"
        assert not any( "action" in t.lower() for t in texts ), "no Action column (read-only)"

    def test_liveness_cell_carries_raw_ages_tooltip( self, logged_in_page ):
        page = logged_in_page
        _open_panel( page, _composite( _POPULATED_SESSIONS ) )

        # The Liveness cell folds the 4 raw ages into a title= hover tooltip (§5).
        live_cells = page.get_by_test_id( "fleet-status-container" ).locator( "td.fleet-col-liveness" )
        assert live_cells.count() == 4, "one liveness cell per session"
        title = live_cells.nth( 0 ).get_attribute( "title" )
        assert title and "bridge" in title and "freshest" in title, "raw ages in tooltip"


class TestFleetStatusReadOnly:
    """AC4 — pure observability: no mutating controls; ⟳ only re-fetches."""

    def test_no_mutating_controls_in_table( self, logged_in_page ):
        page = logged_in_page
        _open_panel( page, _composite( _POPULATED_SESSIONS ) )

        container = page.get_by_test_id( "fleet-status-container" )
        # The rendered table is pure data — zero buttons / inputs / mutating handlers.
        assert container.locator( "button" ).count() == 0, "no buttons inside the table"
        assert container.locator( "input, select, textarea, a[href]" ).count() == 0, "no interactive/mutating controls"

    def test_refresh_button_refetches_only( self, logged_in_page ):
        page = logged_in_page
        holder = _open_panel( page, _composite( _POPULATED_SESSIONS ) )

        before = holder[ "hits" ]
        page.get_by_test_id( "fleet-status-refresh-btn" ).click()
        page.wait_for_timeout( 200 )
        assert holder[ "hits" ] == before + 1, "⟳ triggers exactly one additional GET (re-fetch, no mutation)"
        # Still a table, nothing destroyed.
        assert page.get_by_test_id( "fleet-status-container" ).locator( "table.fleet-status-table" ).count() == 1


class TestFleetStatusStates:
    """AC5 — the §6.4 render states."""

    def test_unreachable_shows_offline_banner( self, logged_in_page ):
        page = logged_in_page
        _open_panel( page, { "status": "unreachable", "fleet_arbiter": None } )

        container = page.get_by_test_id( "fleet-status-container" )
        assert container.locator( ".fleet-status-offline" ).count() == 1
        assert "Arbiter offline" in container.text_content()
        assert page.locator( "#fleet-status-count" ).text_content().strip() == "0"

    def test_null_fleet_arbiter_shows_offline_banner( self, logged_in_page ):
        page = logged_in_page
        _open_panel( page, _composite( [], fleet_arbiter=False ) )

        assert page.get_by_test_id( "fleet-status-container" ).locator( ".fleet-status-offline" ).count() == 1

    def test_empty_sessions_shows_no_active_sessions( self, logged_in_page ):
        page = logged_in_page
        _open_panel( page, _composite( [] ) )

        container = page.get_by_test_id( "fleet-status-container" )
        assert container.locator( ".fleet-status-empty" ).count() == 1
        assert "No active sessions" in container.text_content()
        assert page.locator( "#fleet-status-count" ).text_content().strip() == "0"

    def test_populated_shows_table_and_count( self, logged_in_page ):
        page = logged_in_page
        _open_panel( page, _composite( _POPULATED_SESSIONS ) )

        assert page.get_by_test_id( "fleet-status-container" ).locator( "table.fleet-status-table" ).count() == 1
        assert page.locator( "#fleet-status-count" ).text_content().strip() == "4"

    def test_state_transition_offline_to_populated( self, logged_in_page ):
        """A later poll that recovers flips the offline banner to the grouped table."""
        page = logged_in_page
        holder = _open_panel( page, { "status": "unreachable", "fleet_arbiter": None } )
        assert page.get_by_test_id( "fleet-status-container" ).locator( ".fleet-status-offline" ).count() == 1

        holder[ "body" ] = json.dumps( _composite( _POPULATED_SESSIONS ) )
        _refresh( page )
        assert page.get_by_test_id( "fleet-status-container" ).locator( "table.fleet-status-table" ).count() == 1


class TestFleetStatusVisual:
    """AC6 — visual snapshot of the populated panel (container only → deterministic)."""

    def test_populated_panel_visual_baseline( self, logged_in_page, assert_snapshot ):
        """
        Snapshot the rendered table container. We snapshot #fleet-status-container
        (NOT the section header) so the live last-updated stamp never enters the
        baseline — the table content is fully deterministic from the stub.

        First-run protocol (per `feedback_baseline_capture_disable_tfe`): submit
        with `--update-snapshots` AND `auto_fix_on_failure: False`.
        """
        page = logged_in_page
        _open_panel( page, _composite( _POPULATED_SESSIONS ) )

        container = page.get_by_test_id( "fleet-status-container" )
        container.locator( "table.fleet-status-table" ).wait_for( state="visible", timeout=5000 )
        # Pass the LOCATOR (not raw bytes) so the visual plugin applies its
        # animations="disabled" + mask handling; explicit .png so the baseline is
        # named correctly (plugin only auto-appends .png when name is None). Repo
        # convention: test_multiplexer_phase6c_section_d_visual.py:161.
        assert_snapshot( container, name="fleet-status-populated.png" )
