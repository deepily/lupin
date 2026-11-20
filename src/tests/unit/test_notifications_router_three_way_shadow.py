"""
Unit tests for the three-way shadow hook in POST /api/notify.

With the switch on, a live yes/no ask starts the challenger after its forecast row is written.
With it off, or for any other ask, nothing starts. The card and the forecast row's arguments never change.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""
import threading
from urllib.parse import urlencode

import pytest

from tests.helpers.notifications_endpoint_harness import a_uuid, make_harness_fixture

harness = make_harness_fixture()

_EMAIL = "someone@example.com"
_UID   = a_uuid( "shadow-target" )
_NID   = a_uuid( "shadow-notification" )


class _Item:
    response_default = "DEFAULT-VALUE"
    def to_dict( self ): return { "id": _NID }


class _Result:
    response_type = "yes_no"
    category      = "permission"
    confidence    = 0.9
    metadata      = {}
    def to_hint_dict( self, threshold, metric, always_yes=None ):
        return { "state": "ready", "retrieval_metric": metric, "strategy": "s", "category": "permission", "predicted_value": "yes", "confidence": 0.9 }


@pytest.fixture
def wired( harness, monkeypatch ):
    import cosa.rest.routers.notifications as notif
    import cosa.rest.user_service as user_service
    import cosa.agents.prediction_engine as pe

    state = { "enabled_switch": True, "shadow_calls": [], "forecasts": [], "order": [], "done": threading.Event(), "switch_raises": False }

    monkeypatch.setattr( user_service, "get_user_by_email", lambda email: { "id": _UID, "uid": "UID-VALUE" } )
    monkeypatch.setattr( notif, "_persist_response_required_sync", lambda *a: _NID )
    monkeypatch.setattr( notif, "_mark_notification_expired_sync", lambda nid: None )
    monkeypatch.setattr( notif, "_voice_persona_for_sender_id", lambda sid: { "name": "P", "icon": "I" } )
    monkeypatch.setattr( notif, "pending_responses", {} )

    class _Engine:
        confidence_threshold = 0.5
        hint_voting_enabled  = False
        retrieval_metric     = "dot"
        enabled              = True
        def always_yes_rate( self, recipient_id ): return None
        def predict( self, nd ): return _Result()
        def record_forecast( self, notification_id, nd, **kw ):
            state[ "order" ].append( "forecast" )
            state[ "forecasts" ].append( kw )
        @property
        def three_way_enabled( self ):
            if state[ "switch_raises" ]: raise RuntimeError( "switch unreadable" )
            return state[ "enabled_switch" ]
        def record_three_way_shadow( self, notification_id, nd, asked_at=None ):
            state[ "order" ].append( "shadow" )
            state[ "shadow_calls" ].append( ( notification_id, nd ) )
            state[ "done" ].set()

    engine = _Engine()
    monkeypatch.setattr( pe, "get_prediction_engine", lambda: engine )
    harness.ws.returns( "is_user_connected", True )
    harness.ws.returns( "get_user_connection_count", 1 )
    harness.ws.returns( "emit_to_user_or_listener_sync", { "listener_delivered": False } )
    harness.queue.returns( "push_notification", _Item() )
    return state


def _post( harness, **params ):
    base = { "message": "MESSAGE-VALUE", "title": "TITLE-VALUE", "target_user": _EMAIL, "response_requested": "true",
             "response_type": "yes_no", "timeout_seconds": 1, "response_default": "D" }
    base.update( params )
    return harness.client.post( "/api/notify?" + urlencode( base ) )


def test_with_the_switch_on_a_yes_no_ask_runs_the_challenger_after_its_forecast_row( harness, wired ):
    _post( harness )
    assert wired[ "done" ].wait( 5 )
    nid, nd = wired[ "shadow_calls" ][ 0 ]
    assert nid == _NID and nd[ "message" ] == "MESSAGE-VALUE" and nd[ "title" ] == "TITLE-VALUE"
    assert nd[ "response_type" ] == "yes_no" and nd[ "recipient_id" ] == str( _UID )
    assert wired[ "order" ] == [ "forecast", "shadow" ]


def test_the_card_and_the_forecast_row_are_the_same_with_the_switch_on_or_off( harness, wired ):
    _post( harness )
    wired[ "done" ].wait( 5 )
    on_hint, on_kw = harness.queue.call_to( "push_notification" ).kwargs[ "prediction_hint" ], dict( wired[ "forecasts" ][ 0 ] )
    assert on_hint[ "predicted_value" ] == "yes" and on_hint[ "confidence" ] == 0.9
    wired[ "enabled_switch" ] = False
    wired[ "forecasts" ].clear()
    _post( harness )
    off_kw = dict( wired[ "forecasts" ][ 0 ] )
    on_kw.pop( "prediction_result" ); off_kw.pop( "prediction_result" )
    assert on_kw == off_kw
    assert "three_way_shadow" not in on_hint and "three_way_shadow" not in on_kw


def test_with_the_switch_off_nothing_runs( harness, wired ):
    wired[ "enabled_switch" ] = False
    _post( harness )
    assert wired[ "shadow_calls" ] == [] and wired[ "order" ] == [ "forecast" ]


def test_a_card_that_is_not_yes_no_does_not_run_it( harness, wired ):
    _post( harness, response_type="open_ended" )
    assert wired[ "shadow_calls" ] == []


def test_an_injected_hint_does_not_run_it( harness, wired ):
    _post( harness, prediction_hint_override='{"state": "ready", "predicted_value": "yes", "confidence": 0.9}' )
    assert wired[ "shadow_calls" ] == []


def test_an_unreadable_switch_never_breaks_the_ask( harness, wired ):
    wired[ "switch_raises" ] = True
    response = _post( harness )
    assert response.status_code == 200 and wired[ "shadow_calls" ] == []
