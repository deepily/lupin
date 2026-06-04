"""
E2E UI test for the prediction-hint thumbs up/down vote flow.

This is the test Rick asked for so he never again has to wait for a real worker
question to surface bugs in this path. It renders a hinted notification's vote
controls via the REAL frontend render function (`buildPredictionHintSection`,
which also stashes the per-notification vote context), then clicks 👍🏼/👎🏼 in a
real browser and asserts the vote round-trips to the real server (POST → 200).

Covers the two production bugs found by hand:
  - the 404 (button had no capture endpoint / wrong inline-onclick global)
  - the 422 (empty client question — endpoint now resolves/accepts it)

We drive the render directly (rather than waiting on a WebSocket-delivered,
response-blocking notification) so the test is deterministic and fast — it still
exercises the exact integration that broke: render → button wiring → votePrediction
→ /api/notify/prediction-vote → CBR write.

Venue: :8000 (writes a CBR case via the real endpoint).
"""

from .conftest import BASE_URL


# Renders the real vote controls for a fabricated hinted notification and appends them
# to the page. buildPredictionHintSection() ALSO stashes the vote context that
# votePrediction() reads, so the subsequent click POSTs a complete body.
_RENDER_HINT_JS = """( args ) => {
    const ui = window.notificationsUI;
    if ( !ui || typeof ui.buildPredictionHintSection !== 'function' ) return 'no-ui';
    const notif = {
        id              : args.id,
        message         : args.message,
        response_type   : 'yes_no',
        prediction_hint : { predicted_value: 'yes', confidence: 0.9,
                            strategy: 'cbr_majority_vote', category: 'deploy' },
    };
    const html = ui.buildPredictionHintSection( notif );
    const host = document.createElement( 'div' );
    host.setAttribute( 'data-testid', 'e2e-hint-host' );
    host.innerHTML = html;
    document.body.appendChild( host );
    return 'ok';
}"""


class TestPredictionHintVoteE2E:
    """End-to-end: real hint render → vote button → click → recorded by the server."""

    def test_thumbs_up_records_approved( self, logged_in_page ):
        """Clicking 👍🏼 POSTs to the vote endpoint and gets 200 / ratification_state=approved."""
        page = logged_in_page
        page.goto( f"{BASE_URL}/app/notifications" )
        page.wait_for_load_state( "networkidle" )

        rendered = page.evaluate( _RENDER_HINT_JS, { "id": "e2e-hint-up", "message": "E2E: ship the release?" } )
        assert rendered == "ok", f"hint render failed: {rendered}"

        up = page.get_by_test_id( "prediction-vote-up" )
        up.wait_for( state="visible", timeout=10000 )
        assert "👍" in ( up.inner_text() or "" )                      # thumbs-up glyph present

        with page.expect_response(
            lambda r: "/api/notify/prediction-vote/" in r.url and r.request.method == "POST"
        ) as resp_info:
            up.click()
        resp = resp_info.value
        assert resp.status == 200, f"vote POST returned {resp.status}"
        body = resp.json()
        assert body[ "status" ] == "success"
        assert body[ "vote" ] == "up" and body[ "ratification_state" ] == "approved"

        page.wait_for_timeout( 400 )
        container = page.get_by_test_id( "prediction-hint-vote" )
        assert "voted" in ( container.get_attribute( "class" ) or "" )

    def test_thumbs_down_records_rejected_no_console_error( self, logged_in_page ):
        """Clicking 👎🏼 records 'rejected' AND logs no 404/422 console error (the two bugs)."""
        page   = logged_in_page
        errors = []
        page.on( "console", lambda m: errors.append( m.text ) if m.type == "error" else None )

        page.goto( f"{BASE_URL}/app/notifications" )
        page.wait_for_load_state( "networkidle" )
        rendered = page.evaluate( _RENDER_HINT_JS, { "id": "e2e-hint-down", "message": "E2E: ship the release?" } )
        assert rendered == "ok", f"hint render failed: {rendered}"

        down = page.get_by_test_id( "prediction-vote-down" )
        down.wait_for( state="visible", timeout=10000 )
        with page.expect_response(
            lambda r: "/api/notify/prediction-vote/" in r.url and r.request.method == "POST"
        ) as resp_info:
            down.click()
        resp = resp_info.value
        assert resp.status == 200, f"vote POST returned {resp.status}"
        assert resp.json()[ "ratification_state" ] == "rejected"

        page.wait_for_timeout( 400 )
        offending = [ e for e in errors if "PRED-VOTE" in e or "404" in e or "422" in e ]
        assert not offending, f"vote produced console errors: {offending}"
