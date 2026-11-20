"""
Unit tests for GET /api/notify/prediction-hint/{notification_id}.

The route hands the read to context_hint.read_payload, which has its own database tests.
So what is asserted here is the route's own claims: the display switch, the status codes and the shape.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""

import pytest

from tests.helpers.notifications_endpoint_harness import FROZEN_TIMESTAMP, a_uuid, assert_no_accidental_500, make_harness_fixture

harness = make_harness_fixture()

_NID = a_uuid( "hint-notification" )
_URL = f"/api/notify/prediction-hint/{_NID}"


@pytest.fixture
def wired( monkeypatch ):
    import cosa.agents.prediction_engine as pe
    import cosa.agents.prediction_engine.context_baseline as cb
    import cosa.agents.prediction_engine.context_hint as ch

    state = { "display": True, "payload": { "state": "forecasting" }, "reads": [], "raises": None }

    class _Engine:
        retrieval_metric = "cosine"

    def read( factory, nid, now, metric ):
        state[ "reads" ].append( ( nid, metric ) )
        if state[ "raises" ] is not None: raise state[ "raises" ]
        return state[ "payload" ]

    monkeypatch.setattr( cb, "context_display_enabled", lambda: state[ "display" ] )
    monkeypatch.setattr( ch, "read_payload", read )
    monkeypatch.setattr( pe, "get_prediction_engine", lambda: _Engine() )
    return state


def test_the_card_s_current_payload_comes_back_with_the_metric_the_engine_uses( harness, wired ):
    r = harness.client.get( _URL )
    assert_no_accidental_500( r )
    assert r.status_code == 200
    assert r.json() == { "status": "success", "notification_id": _NID, "context_forecast": { "state": "forecasting" }, "timestamp": FROZEN_TIMESTAMP }
    assert wired[ "reads" ] == [ ( _NID, "cosine" ) ]


def test_with_display_off_the_payload_is_null_and_the_database_is_not_read( harness, wired ):
    wired[ "display" ] = False
    r = harness.client.get( _URL )
    assert r.status_code == 200 and r.json()[ "context_forecast" ] is None and wired[ "reads" ] == []


def test_a_notification_id_that_is_not_a_uuid_is_refused( harness, wired ):
    assert harness.client.get( "/api/notify/prediction-hint/not-a-uuid" ).status_code == 422


def test_an_unknown_notification_is_a_404( harness, wired ):
    wired[ "payload" ] = None
    assert harness.client.get( _URL ).status_code == 404


def test_a_failed_read_is_a_500_that_names_the_cause( harness, wired ):
    wired[ "raises" ] = RuntimeError( "database down" )
    r = harness.client.get( _URL )
    assert r.status_code == 500 and "database down" in r.json()[ "detail" ]
