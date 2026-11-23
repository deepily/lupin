"""
The capture fields: how an answer was given, stored beside the answer.

The route travels as a top-level `input_route` request key and is stored in the notification's
response_value beside "value". Four claims are pinned here, each against the real function:
  - the door stores a route only behind `notification capture fields enabled`;
  - with the switch off the stored row is exactly today's (literal expected dicts, not a re-derivation);
  - a typed answer equal to an option label is stored as typed, never as a click;
  - an old row reads "unknown" for every field except `recommendation`, which is derived from its options.
"""

import os
import sys
import uuid

import pytest

lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path: sys.path.insert( 0, src_path )

import cosa.rest.routers.notifications as notif
from cosa.agents.prediction_engine.episode_view import UNKNOWN_FIELD, capture_fields
from cosa.utils.notification_utils import INPUT_ROUTES, normalize_input_route
from tests.helpers.notifications_endpoint_harness import a_uuid, make_harness_fixture

harness = make_harness_fixture()

_NID       = a_uuid( "capture-fields-notification" )
_RECIPIENT = "99999999-8888-4777-8666-555555555555"
_BY        = { "user_id": _RECIPIENT, "account_email": None, "method": "jwt" }


# ---------------------------------------------------------------- the route check

@pytest.mark.parametrize( "route", INPUT_ROUTES )
def test_each_of_the_four_routes_is_kept( route ):
    assert normalize_input_route( route ) == route


def test_the_four_routes_are_click_typed_comment_voice():
    assert INPUT_ROUTES == ( "click", "typed", "comment", "voice" )


def test_a_per_question_map_is_kept_as_a_copy():
    raw = { "DB": "typed", "Tags": "click" }
    got = normalize_input_route( raw )
    assert got == raw and got is not raw


@pytest.mark.parametrize( "raw", [ None, "", "proxy", "timeout_default", "CLICK", 7, [ "click" ], {}, { "DB": "proxy" }, { 1: "click" }, { "DB": None } ] )
def test_anything_else_is_dropped( raw ):
    assert normalize_input_route( raw ) is None


# ---------------------------------------------------------------- the stored dict

def test_a_string_answer_carries_the_route_beside_its_value():
    assert notif._stored_response_dict( "yes", _BY, "click" ) == { "value": "yes", "source": "ui", "input_route": "click", "answered_by": _BY }


def test_a_dict_answer_carries_the_route_and_the_callers_dict_is_not_changed():
    sent = { "value": "x", "source": "ui" }
    got  = notif._stored_response_dict( sent, None, "voice" )
    assert got == { "value": "x", "source": "ui", "input_route": "voice" } and sent == { "value": "x", "source": "ui" }


def test_a_non_string_non_dict_answer_is_wrapped_with_the_route():
    assert notif._stored_response_dict( [ 1 ], None, "click" ) == { "value": [ 1 ], "source": "ui", "input_route": "click" }


def test_a_per_question_route_is_stored_whole():
    route = { "DB": "typed", "Tags": "click" }
    assert notif._stored_response_dict( '{"answers": {}}', _BY, route )[ "input_route" ] == route


@pytest.mark.parametrize( "value, expected", [
    ( "yes",                     { "value": "yes", "source": "ui" } ),
    ( '{"answers":{"DB":"PG"}}', { "value": '{"answers":{"DB":"PG"}}', "source": "ui" } ),
    ( { "value": "x" },          { "value": "x" } ),
    ( [ 1 ],                     [ 1 ] ),
] )
def test_with_no_route_the_stored_row_is_exactly_todays( value, expected ):
    assert notif._stored_response_dict( value ) == expected
    with_by = notif._stored_response_dict( value, _BY )
    assert "input_route" not in with_by if isinstance( with_by, dict ) else True
    assert with_by == ( { **expected, "answered_by": _BY } if isinstance( expected, dict ) else { "value": [ 1 ], "source": "ui", "answered_by": _BY } )


def test_a_typed_answer_equal_to_a_label_is_stored_as_typed():
    stored = notif._stored_response_dict( '{"answers":{"DB":"PostgreSQL"}}', _BY, { "DB": "typed" } )
    assert stored[ "input_route" ] == { "DB": "typed" } and '"PostgreSQL"' in stored[ "value" ]


# ---------------------------------------------------------------- the worker, to the repository

class _Row:
    state             = "delivered"
    expires_at        = None
    recipient_id      = _RECIPIENT
    job_id            = "JOB"
    sender_id         = "SENDER"
    sender_persona    = "PERSONA"
    response_options  = { "questions": [ { "header": "DB", "options": [ { "label": "PostgreSQL" } ] } ] }


class _Repo:
    def __init__( self ): self.updates = []
    def get_by_id( self, _nid ): return _Row()
    def update_response( self, nid, response_dict ):
        self.updates.append( response_dict )
        return True


@pytest.fixture
def repo( monkeypatch ):
    import lupin_app.main as main_module

    class _Ctx:
        def __enter__( self ): return object()
        def __exit__( self, *exc ): return False

    class _Cfg:
        def get( self, key, default=None, **_kw ): return default

    stub = _Repo()
    monkeypatch.setattr( notif, "get_db", lambda: _Ctx() )
    monkeypatch.setattr( notif, "NotificationRepository", lambda _s: stub )
    monkeypatch.setattr( main_module, "config_mgr", _Cfg() )
    return stub


def test_the_worker_writes_the_route_to_the_row_for_every_route( repo ):
    for route in INPUT_ROUTES:
        repo.updates.clear()
        notif._submit_response_sync( _NID, "yes", _BY, route )
        assert repo.updates == [ { "value": "yes", "source": "ui", "input_route": route, "answered_by": _BY } ]


def test_the_worker_without_a_route_writes_todays_row( repo ):
    notif._submit_response_sync( _NID, "yes", _BY )
    assert repo.updates == [ { "value": "yes", "source": "ui", "answered_by": _BY } ]


# ---------------------------------------------------------------- the switch and the door

def test_the_switch_reads_the_ini_key_and_defaults_off( monkeypatch ):
    import lupin_app.main as main_module

    class _Cfg:
        def __init__( self, value ): self.value = value
        def get( self, key, default=None, **_kw ):
            assert key == "notification capture fields enabled"
            return self.value if self.value is not None else default

    monkeypatch.setattr( main_module, "config_mgr", _Cfg( True ) )
    assert notif._capture_fields_enabled() is True
    monkeypatch.setattr( main_module, "config_mgr", _Cfg( False ) )
    assert notif._capture_fields_enabled() is False
    monkeypatch.setattr( main_module, "config_mgr", _Cfg( None ) )
    assert notif._capture_fields_enabled() is False


def test_an_unreadable_switch_reads_off( monkeypatch ):
    import lupin_app.main as main_module

    class _Broken:
        def get( self, *_a, **_kw ): raise RuntimeError( "settings down" )

    monkeypatch.setattr( main_module, "config_mgr", _Broken() )
    assert notif._capture_fields_enabled() is False


@pytest.fixture
def door( harness, monkeypatch ):
    """Stub the worker and everything after it, and record what the worker is handed."""
    calls = []

    def _submit( notification_id, response_value, answered_by=None, input_route=None ):
        calls.append( input_route )
        return { "recipient_id": "R", "job_id": None, "sender_id": "claude.code@lupin.deepily.ai#aaaa1111", "response_options": { "questions": [] } }

    monkeypatch.setattr( notif, "_submit_response_sync",       _submit )
    monkeypatch.setattr( notif, "_mark_answer_delivered_sync", lambda _n: None )
    monkeypatch.setattr( notif, "_record_review_ruling_sync",  lambda _n: { "rulings_written": 0, "existing": 0, "rejected": [] } )
    monkeypatch.setattr( notif, "_enqueue_extractor_sync",     lambda _n, _r: { "queued": False, "reason": "off" } )
    monkeypatch.setattr( notif, "get_formatted_time_display",  lambda: "T" )
    monkeypatch.setattr( notif, "get_formatted_date_display",  lambda: "D" )
    monkeypatch.setattr( notif, "pending_responses", {} )
    return calls


def _post( harness, route ):
    body = { "notification_id": _NID, "response_value": "yes" }
    if route is not None: body[ "input_route" ] = route
    assert harness.client.post( "/api/notify/response", json=body ).status_code == 200


def test_switch_on_a_valid_route_reaches_the_worker( harness, door, monkeypatch ):
    monkeypatch.setattr( notif, "_capture_fields_enabled", lambda: True )
    _post( harness, "voice" )
    assert door == [ "voice" ]


def test_switch_on_a_per_question_route_reaches_the_worker( harness, door, monkeypatch ):
    monkeypatch.setattr( notif, "_capture_fields_enabled", lambda: True )
    _post( harness, { "DB": "typed" } )
    assert door == [ { "DB": "typed" } ]


@pytest.mark.parametrize( "route", [ "proxy", "timeout_default", 5, None ] )
def test_switch_on_an_invalid_or_missing_route_reaches_the_worker_as_none( harness, door, monkeypatch, route ):
    monkeypatch.setattr( notif, "_capture_fields_enabled", lambda: True )
    _post( harness, route )
    assert door == [ None ]


@pytest.mark.parametrize( "route", [ "click", "typed", { "DB": "click" }, None ] )
def test_switch_off_no_route_ever_reaches_the_worker( harness, door, monkeypatch, route ):
    monkeypatch.setattr( notif, "_capture_fields_enabled", lambda: False )
    _post( harness, route )
    assert door == [ None ]


# ---------------------------------------------------------------- reading it back

def test_a_row_written_before_the_change_reads_unknown_for_the_route():
    old = { "value": "yes", "source": "ui", "answered_by": _BY }
    assert capture_fields( old, None )[ "input_route" ] == UNKNOWN_FIELD
    assert capture_fields( None, None ) == { "input_route": UNKNOWN_FIELD, "recommendation": UNKNOWN_FIELD }
    assert capture_fields( "a bare string", None )[ "input_route" ] == UNKNOWN_FIELD


def test_a_stored_route_reads_back_as_stored():
    assert capture_fields( { "value": "x", "input_route": "typed" }, None )[ "input_route" ] == "typed"
    assert capture_fields( { "value": "x", "input_route": { "DB": "click" } }, None )[ "input_route" ] == { "DB": "click" }


def test_an_old_row_whose_option_carries_a_recommended_flag_reads_that_option():
    options = { "questions": [ { "header": "DB", "options": [ { "label": "MySQL" }, { "label": "PostgreSQL", "recommended": True } ] } ] }
    assert capture_fields( None, options )[ "recommendation" ] == { "DB": [ "PostgreSQL" ] }


def test_an_old_row_whose_label_ends_recommended_reads_that_option():
    options = { "questions": [ { "header": "DB", "options": [ { "label": "MySQL" }, { "label": "PostgreSQL (Recommended)" } ] },
                               { "header": "Cache", "options": [ { "label": "None" } ] } ] }
    assert capture_fields( None, options )[ "recommendation" ] == { "DB": [ "PostgreSQL (Recommended)" ] }


def test_an_old_row_with_neither_reads_unknown():
    options = { "questions": [ { "header": "DB", "options": [ { "label": "MySQL" } ] }, { "header": "Free text" } ] }
    assert capture_fields( None, options )[ "recommendation" ] == UNKNOWN_FIELD
    assert capture_fields( None, { "questions": [] } )[ "recommendation" ] == UNKNOWN_FIELD


def test_reading_a_card_writes_nothing():
    stored  = { "value": "yes" }
    options = { "questions": [ { "header": "DB", "options": [ { "label": "PG", "recommended": True } ] } ] }
    capture_fields( stored, options )
    assert stored == { "value": "yes" } and options == { "questions": [ { "header": "DB", "options": [ { "label": "PG", "recommended": True } ] } ] }
