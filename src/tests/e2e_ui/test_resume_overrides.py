"""
E2E UI tests for Resume-from-checkpoint Model + Effort dropdowns
(Session d8831785, Phase E of 22-model-effort-matrix-plan.md).

Automated verification that:
    1. `isResumableWithOverrides(job)` detects TFE + BFE agents only
    2. `renderResumeOverrideControls(jobId)` emits the two `<select>` elements
       with the documented option sets
    3. Defaults for first-time users are Opus 4.7 / high
    4. localStorage pre-selection round-trips across renders
    5. `saveResumeModelPref` / `saveResumeEffortPref` persist to localStorage
    6. The POST body of `/api/jobs/{id}/resume-from-checkpoint` carries the
       override fields (lead_model_override / worker_model_override /
       thinking_effort) when the user picks specific values
    7. "(default)" effort is NOT sent in the POST body (None maps to omission)

Requires:
    - Test server running on :8000 with the new notifications.js served
    - logged_in_page fixture (conftest.py) — authenticates an ephemeral test user

Run:
    ./src/scripts/run-e2e-ui-tests.sh --bg -v -k resume_overrides

or directly:
    PYTHONPATH=src pytest src/tests/e2e_ui/test_resume_overrides.py -v
"""

import json

from .conftest import BASE_URL


# ────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────

def _nav_notifications( page ):
    """Load the notifications page and wait for the UI to be idle."""
    page.goto( f"{BASE_URL}/app/notifications" )
    page.wait_for_load_state( "networkidle" )
    # Ensure window.notificationsUI is initialized
    page.wait_for_function( "() => window.notificationsUI !== undefined", timeout=5000 )


def _clear_prefs( page ):
    """Wipe the two localStorage keys that influence Resume override defaults."""
    page.evaluate( """
        () => {
            localStorage.removeItem( 'notifications_resume_model' );
            localStorage.removeItem( 'notifications_resume_effort' );
        }
    """ )


def _inject_sandbox( page, job_id="tfe-sandbox" ):
    """
    Render the override controls + a Resume button into a freshly created
    sandbox div. Avoids pulling in the full renderJobCard() machinery while
    still exercising the exact code paths we care about for this test.
    """
    page.evaluate( """
        ( jobId ) => {
            const controls = window.notificationsUI.renderResumeOverrideControls( jobId );
            const btn = `<button class="resume-stalled-btn" data-job-id="${jobId}" onclick="window.notificationsUI?.resumeStalledJob( '${jobId}' )">Resume</button>`;
            let sandbox = document.getElementById( 'e2e-sandbox' );
            if ( !sandbox ) {
                sandbox = document.createElement( 'div' );
                sandbox.id = 'e2e-sandbox';
                document.body.appendChild( sandbox );
            }
            sandbox.innerHTML = controls + btn;
        }
    """, job_id )


# ════════════════════════════════════════════════════════════════════════
# 1. isResumableWithOverrides helper
# ════════════════════════════════════════════════════════════════════════

class TestIsResumableWithOverrides:
    """Gate function: only TFE + BFE jobs should get the override dropdowns."""

    def test_tfe_agent_returns_true( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        r = logged_in_page.evaluate(
            "() => window.notificationsUI.isResumableWithOverrides( { agent_type: 'TestFixExpediterJob' } )"
        )
        assert r is True

    def test_bfe_agent_returns_true( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        r = logged_in_page.evaluate(
            "() => window.notificationsUI.isResumableWithOverrides( { agent_type: 'BugFixExpediterJob' } )"
        )
        assert r is True

    def test_other_agent_returns_false( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        r = logged_in_page.evaluate(
            "() => window.notificationsUI.isResumableWithOverrides( { agent_type: 'DeepResearchJob' } )"
        )
        assert r is False

    def test_missing_agent_type_returns_false( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        r = logged_in_page.evaluate(
            "() => window.notificationsUI.isResumableWithOverrides( {} )"
        )
        assert r is False

    def test_null_agent_type_returns_false( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        r = logged_in_page.evaluate(
            "() => window.notificationsUI.isResumableWithOverrides( { agent_type: null } )"
        )
        assert r is False


# ════════════════════════════════════════════════════════════════════════
# 2. renderResumeOverrideControls — option sets + default selections
# ════════════════════════════════════════════════════════════════════════

class TestDropdownRendering:

    def test_both_selects_rendered( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        _clear_prefs( logged_in_page )
        _inject_sandbox( logged_in_page )
        assert logged_in_page.locator( "#e2e-sandbox .resume-model-select" ).count()  == 1
        assert logged_in_page.locator( "#e2e-sandbox .resume-effort-select" ).count() == 1

    def test_model_select_has_three_options( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        _clear_prefs( logged_in_page )
        _inject_sandbox( logged_in_page )
        assert logged_in_page.locator( "#e2e-sandbox .resume-model-select option" ).count() == 3

    def test_effort_select_has_six_options( self, logged_in_page ):
        """Effort options: (default), low, medium, high, xhigh, max."""
        _nav_notifications( logged_in_page )
        _clear_prefs( logged_in_page )
        _inject_sandbox( logged_in_page )
        assert logged_in_page.locator( "#e2e-sandbox .resume-effort-select option" ).count() == 6

    def test_default_model_is_opus_4_7( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        _clear_prefs( logged_in_page )
        _inject_sandbox( logged_in_page )
        value = logged_in_page.locator( "#e2e-sandbox .resume-model-select" ).input_value()
        assert value == "claude-opus-4-7"

    def test_default_effort_is_high( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        _clear_prefs( logged_in_page )
        _inject_sandbox( logged_in_page )
        value = logged_in_page.locator( "#e2e-sandbox .resume-effort-select" ).input_value()
        assert value == "high"

    def test_localStorage_preselects_model( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        logged_in_page.evaluate(
            "() => localStorage.setItem( 'notifications_resume_model', 'claude-sonnet-4-6' )"
        )
        _inject_sandbox( logged_in_page )
        assert logged_in_page.locator( "#e2e-sandbox .resume-model-select" ).input_value() == "claude-sonnet-4-6"

    def test_localStorage_preselects_effort( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        logged_in_page.evaluate(
            "() => localStorage.setItem( 'notifications_resume_effort', 'xhigh' )"
        )
        _inject_sandbox( logged_in_page )
        assert logged_in_page.locator( "#e2e-sandbox .resume-effort-select" ).input_value() == "xhigh"


# ════════════════════════════════════════════════════════════════════════
# 3. Save handlers — onchange persistence
# ════════════════════════════════════════════════════════════════════════

class TestSaveHandlers:

    def test_saveResumeModelPref_writes_to_localStorage( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        _clear_prefs( logged_in_page )
        logged_in_page.evaluate(
            "() => window.notificationsUI.saveResumeModelPref( 'claude-haiku-4-5-20251001' )"
        )
        stored = logged_in_page.evaluate(
            "() => localStorage.getItem( 'notifications_resume_model' )"
        )
        assert stored == "claude-haiku-4-5-20251001"

    def test_saveResumeEffortPref_writes_to_localStorage( self, logged_in_page ):
        _nav_notifications( logged_in_page )
        _clear_prefs( logged_in_page )
        logged_in_page.evaluate(
            "() => window.notificationsUI.saveResumeEffortPref( 'max' )"
        )
        stored = logged_in_page.evaluate(
            "() => localStorage.getItem( 'notifications_resume_effort' )"
        )
        assert stored == "max"

    def test_onchange_triggers_save( self, logged_in_page ):
        """Selecting a new dropdown value fires the onchange handler → localStorage update."""
        _nav_notifications( logged_in_page )
        _clear_prefs( logged_in_page )
        _inject_sandbox( logged_in_page )
        logged_in_page.locator( "#e2e-sandbox .resume-model-select" ).select_option( "claude-sonnet-4-6" )
        logged_in_page.locator( "#e2e-sandbox .resume-effort-select" ).select_option( "xhigh" )
        assert logged_in_page.evaluate(
            "() => localStorage.getItem( 'notifications_resume_model' )"
        ) == "claude-sonnet-4-6"
        assert logged_in_page.evaluate(
            "() => localStorage.getItem( 'notifications_resume_effort' )"
        ) == "xhigh"


# ════════════════════════════════════════════════════════════════════════
# 4. POST body — overrides flow through resumeStalledJob
# ════════════════════════════════════════════════════════════════════════

class TestResumePOSTBody:
    """
    Click Resume on a synthetic stalled card and intercept the POST to
    /api/jobs/{id}/resume-from-checkpoint. Assert the override fields
    land in the request body.
    """

    def _run_and_capture( self, page, model_value, effort_value ):
        """
        Set up dropdowns at the given values, click Resume, intercept POST.
        Returns the parsed JSON body.
        """
        _nav_notifications( page )
        _clear_prefs( page )
        _inject_sandbox( page, job_id="tfe-intercept" )

        # Select dropdown values (empty string clears selection)
        page.locator( "#e2e-sandbox .resume-model-select" ).select_option( model_value )
        page.locator( "#e2e-sandbox .resume-effort-select" ).select_option( effort_value )

        # Auto-accept the confirm() dialog that gates resumeStalledJob
        page.on( "dialog", lambda d: d.accept() )

        captured = {}

        def handle( route, request ):
            if request.method == "POST" and "resume-from-checkpoint" in request.url:
                captured[ "body" ] = request.post_data
                route.fulfill(
                    status       = 200,
                    content_type = "application/json",
                    body         = json.dumps( {
                        "status"           : "resumed",
                        "resumed_job_id"   : "tfe-mockresumed",
                        "phase_name"       : "phase_3",
                        "resume_from_phase": 3,
                        "original_job_id"  : "tfe-intercept",
                        "resume_count"     : 1,
                    } ),
                )
            else:
                route.continue_()

        page.route( "**/api/jobs/**", handle )

        page.locator( "#e2e-sandbox .resume-stalled-btn" ).click()
        # Give the async POST a moment to fire + the route handler to capture it
        page.wait_for_function(
            "() => document.querySelector( '#e2e-sandbox .resume-stalled-btn' ).disabled === true",
            timeout=3000,
        )
        page.wait_for_timeout( 500 )

        assert "body" in captured, "Resume POST was not intercepted"
        return json.loads( captured[ "body" ] or "{}" )

    def test_explicit_model_and_effort_land_in_body( self, logged_in_page ):
        body = self._run_and_capture(
            logged_in_page, "claude-haiku-4-5-20251001", "max"
        )
        assert body.get( "lead_model_override" )   == "claude-haiku-4-5-20251001"
        assert body.get( "worker_model_override" ) == "claude-haiku-4-5-20251001"
        assert body.get( "thinking_effort" )       == "max"

    def test_default_effort_omitted_from_body( self, logged_in_page ):
        """Selecting '(default)' effort → the thinking_effort key is NOT sent."""
        body = self._run_and_capture(
            logged_in_page, "claude-opus-4-7", ""
        )
        # Model still sent (user picked a value)
        assert body.get( "lead_model_override" ) == "claude-opus-4-7"
        # Effort omitted (empty value falls through to no key)
        assert "thinking_effort" not in body

    def test_sonnet_and_high_flow_through( self, logged_in_page ):
        body = self._run_and_capture(
            logged_in_page, "claude-sonnet-4-6", "high"
        )
        assert body.get( "lead_model_override" )   == "claude-sonnet-4-6"
        assert body.get( "worker_model_override" ) == "claude-sonnet-4-6"
        assert body.get( "thinking_effort" )       == "high"
