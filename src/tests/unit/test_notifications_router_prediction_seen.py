"""
Unit tests for POST /api/notify/prediction-seen/{notification_id}.

The route and the real PredictionLogRepository.record_seen run together. Only the database session is
replaced, by one whose query chain hands back a row object. So the real code decides three things.
The first call stores its time, the second is ignored, and an unreported event stays null.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""

import datetime as dt
import types

import pytest

from tests.helpers.notifications_endpoint_harness import (
    FROZEN_TIMESTAMP, a_uuid, assert_no_accidental_500, make_harness_fixture )

import cosa.rest.db.repositories.prediction_log_repository as plr

harness = make_harness_fixture()

_NID = a_uuid( "seen-notification" )
_URL = f"/api/notify/prediction-seen/{_NID}"


class _Query:
    def __init__( self, row ): self._row = row
    def filter( self, *_a ):   return self
    def with_for_update( self ): return self
    def first( self ):         return self._row


class _Session:
    def __init__( self, row ):
        self._row   = row
        self.locked = 0
        self.flushed = 0
    def query( self, _model ): return _Query( self._row )
    def flush( self ):         self.flushed += 1


@pytest.fixture
def row( monkeypatch ):
    """A forecast row with both seen times null, wired in behind the route."""
    r       = types.SimpleNamespace( rendered_at=None, fold_opened_at=None, draft_at_reveal=None )
    session = _Session( r )
    real    = plr.PredictionLogRepository
    monkeypatch.setattr( plr, "PredictionLogRepository", lambda _s: real( session ) )
    r.session = session
    return r


def _post( harness, **body ):
    r = harness.client.post( _URL, json=body )
    assert_no_accidental_500( r )
    return r


class TestStoringTheFirstTimes:

    def test_rendered_is_stored_and_fold_open_stays_null_when_never_called( self, harness, row ):
        r = _post( harness, rendered=True )
        assert r.status_code == 200
        body = r.json()
        assert body[ "status" ]               == "success"
        assert body[ "notification_id" ]      == _NID
        assert body[ "rendered_recorded" ]    is True
        assert body[ "fold_opened_recorded" ] is False
        assert body[ "timestamp" ]            == FROZEN_TIMESTAMP
        assert isinstance( row.rendered_at, dt.datetime ) and row.rendered_at.tzinfo is not None
        assert row.fold_opened_at is None
        assert row.session.flushed == 1

    def test_fold_open_is_stored_on_its_own_call_after_rendered( self, harness, row ):
        _post( harness, rendered=True )
        rendered_first = row.rendered_at
        r = _post( harness, fold_opened=True ).json()
        assert r[ "fold_opened_recorded" ] is True
        assert r[ "rendered_recorded" ]    is False
        assert row.rendered_at == rendered_first
        assert isinstance( row.fold_opened_at, dt.datetime )

    def test_both_events_in_one_call_are_both_stored( self, harness, row ):
        r = _post( harness, rendered=True, fold_opened=True ).json()
        assert ( r[ "rendered_recorded" ], r[ "fold_opened_recorded" ] ) == ( True, True )
        assert row.rendered_at is not None and row.fold_opened_at is not None


class TestLaterCallsAreIgnored:

    def test_a_second_rendered_call_keeps_the_first_time( self, harness, row ):
        first = dt.datetime( 2020, 1, 1, tzinfo=dt.timezone.utc )
        row.rendered_at = first
        r = _post( harness, rendered=True ).json()
        assert r[ "rendered_recorded" ] is False
        assert row.rendered_at == first, "the stored time must not move"

    def test_a_second_fold_open_call_keeps_the_first_time( self, harness, row ):
        first = dt.datetime( 2020, 1, 2, tzinfo=dt.timezone.utc )
        row.fold_opened_at = first
        r = _post( harness, fold_opened=True ).json()
        assert r[ "fold_opened_recorded" ] is False
        assert row.fold_opened_at == first

    def test_an_empty_body_stores_nothing( self, harness, row ):
        r = _post( harness ).json()
        assert ( r[ "rendered_recorded" ], r[ "fold_opened_recorded" ] ) == ( False, False )
        assert row.rendered_at is None and row.fold_opened_at is None


class TestDraftAtReveal:

    def test_a_draft_is_stored_with_the_fold_open_and_reported( self, harness, row ):
        r = _post( harness, fold_opened=True, draft_at_reveal={ "value": "yes" } ).json()
        assert r[ "draft_recorded" ] is True
        assert row.draft_at_reveal == { "value": "yes" }
        assert row.fold_opened_at is not None

    def test_the_first_draft_wins_over_a_later_one( self, harness, row ):
        _post( harness, fold_opened=True, draft_at_reveal={ "value": "yes" } )
        r = _post( harness, fold_opened=True, draft_at_reveal={ "value": "no" } ).json()
        assert r[ "draft_recorded" ] is False
        assert row.draft_at_reveal == { "value": "yes" }

    def test_a_request_without_the_field_behaves_as_before( self, harness, row ):
        r = _post( harness, fold_opened=True ).json()
        assert r[ "draft_recorded" ] is False
        assert row.draft_at_reveal is None
        assert ( r[ "rendered_recorded" ], r[ "fold_opened_recorded" ] ) == ( False, True )
        assert row.fold_opened_at is not None and row.rendered_at is None

    def test_a_draft_sent_without_a_fold_open_is_not_stored( self, harness, row ):
        r = _post( harness, rendered=True, draft_at_reveal={ "value": "yes" } ).json()
        assert r[ "draft_recorded" ] is False
        assert row.draft_at_reveal is None

    def test_a_draft_after_the_fold_time_was_stored_is_not_stored( self, harness, row ):
        row.fold_opened_at = dt.datetime( 2020, 1, 2, tzinfo=dt.timezone.utc )
        r = _post( harness, fold_opened=True, draft_at_reveal={ "value": "yes" } ).json()
        assert r[ "draft_recorded" ] is False
        assert row.draft_at_reveal is None

    @pytest.mark.parametrize( "draft", [ {}, { "answer": "yes" }, { "value": "x" * 5000 } ] )
    def test_a_draft_without_a_value_or_over_the_size_bound_answers_422( self, harness, row, draft ):
        r = harness.client.post( _URL, json={ "fold_opened": True, "draft_at_reveal": draft } )
        assert r.status_code == 422
        assert row.draft_at_reveal is None and row.fold_opened_at is None

    def test_an_explicit_null_draft_is_accepted_and_stores_nothing( self, harness, row ):
        r = harness.client.post( _URL, json={ "fold_opened": True, "draft_at_reveal": None } )
        assert r.status_code == 200
        assert r.json()[ "draft_recorded" ] is False
        assert row.draft_at_reveal is None and row.fold_opened_at is not None

    def test_a_draft_that_is_not_an_object_answers_422( self, harness, row ):
        r = harness.client.post( _URL, json={ "fold_opened": True, "draft_at_reveal": "yes" } )
        assert r.status_code == 422
        assert row.draft_at_reveal is None and row.fold_opened_at is None


class TestRefusals:

    def test_no_forecast_row_answers_404( self, harness, monkeypatch ):
        real = plr.PredictionLogRepository
        monkeypatch.setattr( plr, "PredictionLogRepository", lambda _s: real( _Session( None ) ) )
        r = harness.client.post( _URL, json={ "rendered": True } )
        assert r.status_code == 404
        assert _NID in r.json()[ "detail" ]

    def test_a_non_uuid_id_answers_422( self, harness ):
        r = harness.client.post( "/api/notify/prediction-seen/not-a-uuid", json={ "rendered": True } )
        assert r.status_code == 422

    def test_a_database_failure_answers_500_with_the_cause( self, harness ):
        harness.fail_db( RuntimeError( "connection reset" ) )
        r = harness.client.post( _URL, json={ "rendered": True } )
        assert r.status_code == 500
        assert "connection reset" in r.json()[ "detail" ]
