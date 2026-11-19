"""
Unit tests for the ask-time forecast ledger hook in POST /api/notify.

Every ask writes exactly one forecast row before the hint is pushed, whichever path it took. The paths are a
forecast, a cold start, a disabled engine, a predictor error and a test override. These tests give the engine a
record_forecast that logs what the router handed it. It also logs whether the card had been pushed yet.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""
import json
from urllib.parse import urlencode

import pytest

from tests.helpers.notifications_endpoint_harness import a_uuid, make_harness_fixture

harness = make_harness_fixture()

_EMAIL = "someone@example.com"
_UID   = a_uuid( "ledger-target" )
_NID   = a_uuid( "ledger-notification" )


class _Item:
    response_default = "DEFAULT-VALUE"
    def to_dict( self ): return { "id": _NID }


class _Result:
    """Stands in for a PredictionResult: the router reads confidence, metadata and to_hint_dict."""
    response_type = "yes_no"
    category      = "permission"
    def __init__( self, confidence ):
        self.confidence = confidence
        self.metadata   = {}
    def to_hint_dict( self, threshold, metric, always_yes=None ):
        state = "ready" if self.confidence >= threshold else "below_threshold"
        hint  = { "state": state, "retrieval_metric": metric, "strategy": "s", "category": "permission" }
        if state == "ready": hint.update( predicted_value="yes", confidence=self.confidence )
        if always_yes is not None: hint[ "always_yes_rate" ] = always_yes
        return hint


@pytest.fixture
def wired( harness, monkeypatch ):
    import cosa.rest.routers.notifications as notif
    import cosa.rest.user_service as user_service
    import cosa.agents.prediction_engine as pe

    state = { "forecasts": [], "pushed_at_forecast": [], "enabled": True, "result": _Result( 0.9 ), "predict_raises": None,
              "forecast_raises": None, "predict_calls": [], "yes_rate": { "yes": 52, "n": 59, "rate": 0.8814 },
              "yes_rate_calls": [] }

    monkeypatch.setattr( user_service, "get_user_by_email", lambda email: { "id": _UID, "uid": "UID-VALUE" } )
    monkeypatch.setattr( notif, "_persist_response_required_sync", lambda *a: _NID )
    monkeypatch.setattr( notif, "_mark_notification_expired_sync", lambda nid: None )
    monkeypatch.setattr( notif, "_voice_persona_for_sender_id", lambda sid: { "name": "P", "icon": "I" } )
    monkeypatch.setattr( notif, "pending_responses", {} )

    class _Engine:
        confidence_threshold = 0.5
        hint_voting_enabled  = False
        retrieval_metric     = "dot"
        def always_yes_rate( self, recipient_id ):
            state[ "yes_rate_calls" ].append( recipient_id )
            return state[ "yes_rate" ]
        @property
        def enabled( self ): return state[ "enabled" ]
        def predict( self, nd ):
            state[ "predict_calls" ].append( nd )
            if state[ "predict_raises" ] is not None: raise state[ "predict_raises" ]
            return state[ "result" ]
        def record_forecast( self, notification_id, nd, **kw ):
            if state[ "forecast_raises" ] is not None: raise state[ "forecast_raises" ]
            state[ "forecasts" ].append( ( notification_id, nd, kw ) )
            state[ "pushed_at_forecast" ].append( len( harness.queue.calls_to( "push_notification" ) ) )

    engine = _Engine()
    monkeypatch.setattr( pe, "get_prediction_engine", lambda: engine )

    harness.ws.returns( "is_user_connected", True )
    harness.ws.returns( "get_user_connection_count", 1 )
    harness.ws.returns( "emit_to_user_or_listener_sync", { "listener_delivered": False } )
    harness.queue.returns( "push_notification", _Item() )
    return state


def _post( harness, **params ):
    base = { "message": "MESSAGE-VALUE", "target_user": _EMAIL, "response_requested": "true",
             "response_type": "yes_no", "timeout_seconds": 1, "response_default": "D" }
    base.update( params )
    return harness.client.post( "/api/notify?" + urlencode( base ) )


class TestEveryAskWritesOneRowBeforeTheHint:

    def test_a_forecast_hands_its_result_and_is_written_before_the_push( self, harness, wired ):
        _post( harness )
        assert len( wired[ "forecasts" ] ) == 1
        nid, nd, kw = wired[ "forecasts" ][ 0 ]
        assert nid == _NID
        assert kw[ "prediction_result" ] is wired[ "result" ]
        assert nd[ "message" ] == "MESSAGE-VALUE" and nd[ "response_type" ] == "yes_no"
        assert kw[ "owner_email" ] == _EMAIL
        assert wired[ "pushed_at_forecast" ] == [ 0 ], "the card was already pushed when the row was written"

    def test_the_row_stores_the_same_state_the_card_is_sent( self, harness, wired ):
        _post( harness )
        wired[ "result" ] = _Result( 0.1 )
        _post( harness )
        sent   = [ c.kwargs[ "prediction_hint" ][ "state" ] for c in harness.queue.calls_to( "push_notification" ) ]
        stored = [ f[ 2 ][ "display_decision" ] for f in wired[ "forecasts" ] ]
        assert sent == stored == [ "ready", "below_threshold" ]

    def test_a_weak_forecast_is_sent_with_no_value_and_no_gates( self, harness, wired ):
        wired[ "result" ] = _Result( 0.1 )
        _post( harness )
        hint = harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ]
        assert hint[ "state" ] == "below_threshold" and "predicted_value" not in hint
        assert not any( key.startswith( "auto_submit" ) or key.startswith( "vote_" ) for key in hint )

    def test_a_yes_no_ask_computes_the_always_yes_rate_for_its_recipient_and_stores_and_sends_it( self, harness, wired ):
        _post( harness )
        assert wired[ "yes_rate_calls" ] == [ _UID ]
        assert wired[ "forecasts" ][ 0 ][ 2 ][ "always_yes_rate" ] == wired[ "yes_rate" ]
        assert harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ][ "always_yes_rate" ] == wired[ "yes_rate" ]

    def test_a_card_that_is_not_yes_no_computes_no_rate( self, harness, wired ):
        _post( harness, response_type="open_ended" )
        assert wired[ "yes_rate_calls" ] == []
        assert wired[ "forecasts" ][ 0 ][ 2 ][ "always_yes_rate" ] is None

    def test_a_disabled_engine_writes_a_cold_start_row_named_engine_disabled( self, harness, wired ):
        wired[ "enabled" ] = False
        _post( harness )
        kw = wired[ "forecasts" ][ 0 ][ 2 ]
        assert wired[ "predict_calls" ] == []
        assert kw[ "strategy" ] == "cold_start" and kw[ "abstention_reason" ] == "engine_disabled"
        assert kw[ "display_decision" ] == "unavailable"
        assert "prediction_result" not in kw

    def test_a_predictor_error_writes_a_row_naming_the_exception_class( self, harness, wired ):
        wired[ "predict_raises" ] = KeyError( "boom" )
        r = _post( harness )
        assert r.status_code == 200, "a predictor error must not cost the ask"
        kw = wired[ "forecasts" ][ 0 ][ 2 ]
        assert kw[ "strategy" ] == "error" and kw[ "abstention_reason" ] == "predictor_error: KeyError"
        assert kw[ "display_decision" ] == "unavailable"
        assert harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ][ "state" ] == "unavailable"

    def test_a_test_override_writes_a_test_override_row_and_never_calls_predict( self, harness, wired ):
        _post( harness, prediction_hint_override=json.dumps( { "predicted_value": "yes" } ) )
        kw = wired[ "forecasts" ][ 0 ][ 2 ]
        assert wired[ "predict_calls" ] == []
        assert kw[ "forecast_source" ] == "test_override" and kw[ "strategy" ] == "test_override"
        assert kw[ "abstention_reason" ] == "test_override" and kw[ "display_decision" ] == "ready"

    def test_an_engine_that_cannot_be_built_still_gets_a_ledger_attempt_without_costing_the_ask( self, harness, wired, monkeypatch ):
        import cosa.agents.prediction_engine as pe
        def boom(): raise RuntimeError( "engine down" )
        monkeypatch.setattr( pe, "get_prediction_engine", boom )
        r = _post( harness )
        assert r.status_code == 200
        assert wired[ "forecasts" ] == []

    def test_a_ledger_write_that_raises_does_not_cost_the_ask( self, harness, wired, capsys ):
        wired[ "forecast_raises" ] = RuntimeError( "ledger down" )
        r = _post( harness )
        assert r.status_code == 200
        assert "Forecast ledger error" in capsys.readouterr().out

    def test_the_override_path_builds_its_engine_for_the_ledger( self, harness, wired ):
        """The override skips the engine in the predict branch, so the ledger fetches it itself."""
        _post( harness, prediction_hint_override=json.dumps( { "predicted_value": "no" } ) )
        assert len( wired[ "forecasts" ] ) == 1


class TestAReviewCardIsNeverForecast:
    """A card marked as a review card gets no forecast and no ledger row."""

    _MARKED = json.dumps( { "review_card": True } )

    def test_a_marked_ask_calls_no_predictor_and_writes_no_row_but_the_card_is_still_sent( self, harness, wired ):
        r = _post( harness, response_options=self._MARKED )
        assert r.status_code == 200
        assert wired[ "predict_calls" ] == [] and wired[ "forecasts" ] == [] and wired[ "yes_rate_calls" ] == []
        hint = harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ]
        assert hint[ "state" ] == "insufficient_evidence" and "predicted_value" not in hint, "a payload with no value in it"

    def test_the_same_ask_without_the_marker_is_forecast_and_written( self, harness, wired ):
        _post( harness, response_options=json.dumps( { "review_card": False } ) )
        _post( harness, response_options=json.dumps( { "note": "review_card" } ) )
        assert len( wired[ "predict_calls" ] ) == 2 and len( wired[ "forecasts" ] ) == 2

    def test_a_marked_ask_is_skipped_even_with_a_test_override_hint( self, harness, wired ):
        _post( harness, response_options=self._MARKED, prediction_hint_override=json.dumps( { "predicted_value": "yes" } ) )
        assert wired[ "forecasts" ] == [] and wired[ "predict_calls" ] == []
