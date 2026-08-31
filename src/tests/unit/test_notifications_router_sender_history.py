"""
Unit tests for the six SENDER-HISTORY endpoints — the conversation surface behind the
notifications UI:

    GET    /api/notifications/senders/{user_email}
    GET    /api/notifications/conversation/{sender_id}/{user_email}
    DELETE /api/notifications/conversation/{sender_id}/{user_email}
    GET    /api/notifications/conversation-by-date/{sender_id}/{user_email}
    DELETE /api/notifications/date/{sender_id}/{user_email}/{date_string}
    GET    /api/notifications/sender-dates/{sender_id}/{user_email}

🔴 THE TIMEZONE IS THE THING THESE SIX SHARE, AND IT IS EASY TO TEST BLIND. Four of
them build their OWN ConfigurationManager inside the function, read the app timezone,
and then either serialise every timestamp through it or pass its NAME down so the
database can group by local date. Under UTC — the fixture default — a converted stamp
and an unconverted one are the SAME STRING, so every test here that makes a claim
about conversion sets a non-zero-offset zone first. That is the difference between
asserting the behaviour and asserting that the code ran.

🔴 SOFT DELETE AND HARD DELETE SIT ON ADJACENT ROUTES AND MEAN OPPOSITE THINGS.
DELETE /conversation/... removes rows permanently; DELETE /date/... only sets
is_hidden. Each is asserted by NAME at the repo boundary, because both return a count
and a 200 and are otherwise indistinguishable from outside.

🔴 A 404 HERE MEANS "NO SUCH USER", NEVER "NOTHING FOUND". Every one of these six
returns an empty list, dict or zero count for an empty result — the docstrings say so
explicitly for the delete — so both branches are posed.

Fixture: `tests.helpers.notifications_endpoint_harness`.
"""

import uuid
from datetime import datetime, timezone as _tz
from urllib.parse import quote

import pytest

from tests.helpers.notifications_endpoint_harness import (
    a_uuid, assert_no_accidental_500, make_harness_fixture )

harness = make_harness_fixture()


_SENDER = "claude.code@lupin.deepily.ai#aaaa1111"
_EMAIL  = "someone@example.com"
_UID    = a_uuid( "history-user" )

# 🔴 THE `#` MUST BE PERCENT-ENCODED OR THE REQUEST NEVER REACHES THE HANDLER.
# A real sender id carries a session hash after a `#`, which a URL reads as a
# FRAGMENT — the client drops it and everything after, so the path shortens and
# FastAPI answers 404 from the router. Two of the 404 tests below passed against
# that phantom before this was fixed: they asserted the right CODE from the wrong
# SOURCE. `_S` is the encoded form and is what every path here is built from.
_S = quote( _SENDER, safe="" )


@pytest.fixture( autouse=True )
def user_lookup( monkeypatch, request ):
    """
    Patch `get_user_by_email` on its OWN module — all six handlers import it inside
    the function body, so patching the router's namespace leaves the real lookup (and
    a real database call) running.
    """
    import cosa.rest.user_service as user_service
    state = { "user": { "id": _UID, "uid": "UID-VALUE" }, "calls": [] }

    def _fake( email ):
        state[ "calls" ].append( email )
        return state[ "user" ]

    monkeypatch.setattr( user_service, "get_user_by_email", _fake )
    return state


class _Row:
    """A conversation row whose every field carries a value naming itself."""
    id                 = a_uuid( "conversation-row" )
    sender_id          = "SENDER-ID-VALUE"
    message            = "MESSAGE-VALUE"
    title              = "TITLE-VALUE"
    type               = "TYPE-VALUE"
    priority           = "PRIORITY-VALUE"
    state              = "STATE-VALUE"
    is_hidden          = False
    abstract           = "ABSTRACT-VALUE"
    response_requested = True
    response_type      = "RESPONSE-TYPE-VALUE"
    response_value     = "RESPONSE-VALUE-VALUE"
    job_id             = "JOB-ID-VALUE"
    progress_group_id  = "PROGRESS-GROUP-VALUE"
    # 2026-06-15 04:30 UTC — chosen so a New York conversion lands on the PREVIOUS
    # day (00:30 EDT), which is what makes "converted" and "not converted" different
    # dates rather than merely different hours.
    created_at   = datetime( 2026, 6, 15, 4, 30, tzinfo=_tz.utc )
    delivered_at = datetime( 2026, 6, 15, 5, 45, tzinfo=_tz.utc )
    responded_at = None


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/senders/{user_email}
# ═══════════════════════════════════════════════════════════════════════════════

class TestListingSenders:

    _URL = f"/api/notifications/senders/{_EMAIL}"

    def _activity( self, hours_ago ):
        from datetime import timedelta
        return { "sender_id" : f"SENDER-{hours_ago}H",
                 "count"     : hours_ago,
                 "last_activity": datetime.now( _tz.utc ) - timedelta( hours=hours_ago ) }

    def test_it_returns_the_activity_list_as_the_whole_body( self, harness ):
        """This endpoint returns a bare list, not an envelope — pinned deliberately."""
        harness.repo.returns( "get_sender_last_activities", [ self._activity( 1 ) ] )
        r = harness.client.get( self._URL )
        assert_no_accidental_500( r )
        body = r.json()
        assert isinstance( body, list )
        assert body[ 0 ][ "sender_id" ] == "SENDER-1H"
        assert body[ 0 ][ "count" ]     == 1

    def test_the_last_activity_is_serialised_as_an_iso_string( self, harness ):
        """
        The repo hands back a datetime, which is not JSON. A handler that skipped the
        conversion would 500 on serialisation — so this asserts the STRING, which also
        pins that the conversion happens here rather than by luck.
        """
        harness.repo.returns( "get_sender_last_activities", [ self._activity( 1 ) ] )
        value = harness.client.get( self._URL ).json()[ 0 ][ "last_activity" ]
        assert isinstance( value, str )
        assert value.startswith( "20" )

    def test_the_query_is_scoped_to_the_looked_up_uuid( self, harness ):
        harness.repo.returns( "get_sender_last_activities", [] )
        harness.client.get( self._URL )
        assert harness.repo.call_to( "get_sender_last_activities" ).first == uuid.UUID( _UID )

    def test_the_hours_filter_drops_senders_older_than_the_cutoff( self, harness ):
        """
        The filter runs HERE, not in the repo. One old and one recent sender make
        "filtered" and "returned everything" different answers; a single row could not.
        """
        harness.repo.returns( "get_sender_last_activities",
                              [ self._activity( 1 ), self._activity( 100 ) ] )
        body = harness.client.get( f"{self._URL}?hours=24" ).json()
        assert [ s[ "sender_id" ] for s in body ] == [ "SENDER-1H" ]

    def test_without_the_filter_everything_comes_back( self, harness ):
        """The other side of the same fork — the guard, not just the comprehension."""
        harness.repo.returns( "get_sender_last_activities",
                              [ self._activity( 1 ), self._activity( 100 ) ] )
        assert len( harness.client.get( self._URL ).json() ) == 2

    def test_the_filter_is_NOT_pushed_down_to_the_repo( self, harness ):
        harness.repo.returns( "get_sender_last_activities", [] )
        harness.client.get( f"{self._URL}?hours=24" )
        call = harness.repo.call_to( "get_sender_last_activities" )
        assert call.args == ( uuid.UUID( _UID ), ) and call.kwargs == {}

    def test_an_unknown_user_is_a_404_and_no_query_runs( self, harness, user_lookup ):
        user_lookup[ "user" ] = None
        r = harness.client.get( self._URL )
        assert r.status_code == 404
        assert harness.repo.calls == []

    def test_no_senders_is_an_empty_list_and_not_a_404( self, harness ):
        harness.repo.returns( "get_sender_last_activities", [] )
        r = harness.client.get( self._URL )
        assert r.status_code == 200
        assert r.json() == []

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_sender_last_activities", RuntimeError( "boom" ) )
        assert harness.client.get( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/conversation/{sender_id}/{user_email}
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadingAConversation:

    _URL = f"/api/notifications/conversation/{_S}/{_EMAIL}"

    def test_it_projects_every_field_under_its_own_key( self, harness ):
        harness.repo.returns( "get_sender_conversation", [ _Row() ] )
        r = harness.client.get( self._URL )
        assert_no_accidental_500( r )
        item = r.json()[ 0 ]
        assert item[ "message" ]            == "MESSAGE-VALUE"
        assert item[ "title" ]              == "TITLE-VALUE"
        assert item[ "response_type" ]      == "RESPONSE-TYPE-VALUE"
        assert item[ "response_value" ]     == "RESPONSE-VALUE-VALUE"
        assert item[ "progress_group_id" ]  == "PROGRESS-GROUP-VALUE"
        assert item[ "is_hidden" ]          is False
        assert item[ "response_requested" ] is True

    def test_a_null_timestamp_stays_null_rather_than_becoming_a_string( self, harness ):
        """`responded_at` is None on an unanswered row, and the UI reads null as unanswered."""
        harness.repo.returns( "get_sender_conversation", [ _Row() ] )
        assert harness.client.get( self._URL ).json()[ 0 ][ "responded_at" ] is None

    def test_timestamps_are_converted_into_the_configured_timezone( self, harness ):
        """
        🔴 THE ASSERTION ONLY MEANS SOMETHING AWAY FROM UTC. The row is stamped
        04:30 UTC, which is 00:30 the PREVIOUS DAY in New York — so a handler that
        skipped the conversion returns a different DATE, not merely a different hour.
        """
        harness.set_app_timezone( "America/New_York" )
        harness.repo.returns( "get_sender_conversation", [ _Row() ] )
        item = harness.client.get( self._URL ).json()[ 0 ]
        assert item[ "created_at" ].startswith( "2026-06-15T00:30" )
        assert item[ "time_display" ] == "00:30 EDT"

    def test_the_timestamp_field_mirrors_created_at( self, harness ):
        """Both are emitted; a divergence would silently reorder the chat view."""
        harness.set_app_timezone( "America/New_York" )
        harness.repo.returns( "get_sender_conversation", [ _Row() ] )
        item = harness.client.get( self._URL ).json()[ 0 ]
        assert item[ "timestamp" ] == item[ "created_at" ]

    def test_the_window_defaults_to_twenty_four_hours( self, harness ):
        harness.repo.returns( "get_sender_conversation", [] )
        harness.client.get( self._URL )
        assert harness.repo.call_to( "get_sender_conversation" ).kwargs[ "window_hours" ] == 24

    def test_the_sender_and_the_resolved_recipient_both_scope_the_query( self, harness ):
        """
        Scoping on the sender alone would hand one user another's conversation with
        the same sender — and every seat here talks to the same senders.
        """
        harness.repo.returns( "get_sender_conversation", [] )
        harness.client.get( self._URL )
        call = harness.repo.call_to( "get_sender_conversation" )
        assert call.kwargs[ "sender_id" ]    == _SENDER
        assert call.kwargs[ "recipient_id" ] == uuid.UUID( _UID )

    def test_an_anchor_reaches_the_query_as_a_datetime( self, harness ):
        harness.repo.returns( "get_sender_conversation", [] )
        harness.client.get( f"{self._URL}?anchor=2026-06-15T04:30:00%2B00:00" )
        anchor = harness.repo.call_to( "get_sender_conversation" ).kwargs[ "anchor" ]
        assert anchor == datetime( 2026, 6, 15, 4, 30, tzinfo=_tz.utc )

    def test_a_trailing_Z_anchor_is_accepted( self, harness ):
        """
        Browsers emit `...Z`, which `datetime.fromisoformat` rejected before 3.11 —
        the handler rewrites it. Dropping that rewrite turns every UI request into a
        400, and no other test here would notice.
        """
        harness.repo.returns( "get_sender_conversation", [] )
        r = harness.client.get( f"{self._URL}?anchor=2026-06-15T04:30:00Z" )
        assert r.status_code == 200
        assert harness.repo.call_to( "get_sender_conversation" ).kwargs[ "anchor" ] == \
               datetime( 2026, 6, 15, 4, 30, tzinfo=_tz.utc )

    def test_no_anchor_forwards_none( self, harness ):
        harness.repo.returns( "get_sender_conversation", [] )
        harness.client.get( self._URL )
        assert harness.repo.call_to( "get_sender_conversation" ).kwargs[ "anchor" ] is None

    def test_an_unparseable_anchor_is_a_400_and_no_query_runs( self, harness ):
        r = harness.client.get( f"{self._URL}?anchor=not-a-timestamp" )
        assert r.status_code == 400
        assert harness.repo.calls == []

    def test_reading_a_conversation_writes_nothing( self, harness ):
        harness.repo.returns( "get_sender_conversation", [ _Row() ] )
        harness.client.get( self._URL )
        harness.repo.assert_only_called( "get_sender_conversation" )

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_sender_conversation", RuntimeError( "boom" ) )
        assert harness.client.get( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE /api/notifications/conversation/{sender_id}/{user_email}
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeletingAConversation:

    _URL = f"/api/notifications/conversation/{_S}/{_EMAIL}"

    def test_it_deletes_by_sender_and_reports_the_count( self, harness ):
        harness.repo.returns( "delete_by_sender", 4 )
        r = harness.client.delete( self._URL )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]        == "success"
        assert body[ "deleted_count" ] == 4
        assert body[ "sender_id" ]     == _SENDER

    def test_this_is_the_HARD_delete_not_the_soft_one( self, harness ):
        """
        🔴 THE ADJACENT ROUTE ONLY HIDES. Both return a count and a 200, so the only
        thing separating a permanent delete from a soft one is which repo method was
        reached — asserted by name.
        """
        harness.repo.returns( "delete_by_sender", 1 )
        harness.client.delete( self._URL )
        harness.repo.assert_only_called( "delete_by_sender" )
        harness.repo.assert_never_called( "soft_delete_by_date" )

    def test_the_delete_is_scoped_to_the_resolved_recipient( self, harness ):
        harness.repo.returns( "delete_by_sender", 0 )
        harness.client.delete( self._URL )
        call = harness.repo.call_to( "delete_by_sender" )
        assert call.kwargs[ "sender_id" ]    == _SENDER
        assert call.kwargs[ "recipient_id" ] == uuid.UUID( _UID )

    def test_an_empty_conversation_is_a_success_with_zero_not_a_404( self, harness ):
        """The docstring is explicit: 404 means no such USER, never an empty result."""
        harness.repo.returns( "delete_by_sender", 0 )
        r = harness.client.delete( self._URL )
        assert r.status_code == 200
        assert r.json()[ "deleted_count" ] == 0

    def test_an_unknown_user_is_a_404_and_deletes_nothing( self, harness, user_lookup ):
        user_lookup[ "user" ] = None
        r = harness.client.delete( self._URL )
        assert r.status_code == 404
        assert harness.repo.calls == []

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "delete_by_sender", RuntimeError( "boom" ) )
        assert harness.client.delete( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/conversation-by-date/{sender_id}/{user_email}
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheDateGroupedConversation:

    _URL = f"/api/notifications/conversation-by-date/{_S}/{_EMAIL}"

    def test_it_returns_a_dict_keyed_by_date_with_projected_rows( self, harness ):
        harness.repo.returns( "get_sender_conversations_by_date",
                              { "2026-06-14": [ _Row() ], "2026-06-15": [ _Row(), _Row() ] } )
        r = harness.client.get( self._URL )
        assert_no_accidental_500( r )
        body = r.json()
        assert sorted( body ) == [ "2026-06-14", "2026-06-15" ]
        assert len( body[ "2026-06-14" ] ) == 1
        assert len( body[ "2026-06-15" ] ) == 2
        assert body[ "2026-06-14" ][ 0 ][ "message" ] == "MESSAGE-VALUE"

    def test_the_window_defaults_to_a_week( self, harness ):
        harness.repo.returns( "get_sender_conversations_by_date", {} )
        harness.client.get( self._URL )
        assert harness.repo.call_to( "get_sender_conversations_by_date" ).kwargs[ "window_hours" ] == 168

    def test_the_timezone_NAME_is_passed_down_so_the_grouping_is_local( self, harness ):
        """
        🔴 THE DATE BOUNDARY IS DECIDED IN THE DATABASE, NOT HERE. The zone name
        travels down so rows are grouped by LOCAL date; dropping it groups by UTC and
        a 00:30 EDT message lands under the previous day's accordion header. The
        configured zone is deliberately not the code's own default.
        """
        harness.set_app_timezone( "America/New_York" )
        harness.repo.returns( "get_sender_conversations_by_date", {} )
        harness.client.get( self._URL )
        assert harness.repo.call_to( "get_sender_conversations_by_date" ).kwargs[ "timezone_name" ] == "America/New_York"

    def test_include_hidden_defaults_to_false_and_is_forwarded( self, harness ):
        harness.repo.returns( "get_sender_conversations_by_date", {} )
        harness.client.get( self._URL )
        assert harness.repo.call_to( "get_sender_conversations_by_date" ).kwargs[ "include_hidden" ] is False

    def test_include_hidden_true_is_forwarded_as_a_boolean( self, harness ):
        harness.repo.returns( "get_sender_conversations_by_date", {} )
        harness.client.get( f"{self._URL}?include_hidden=true" )
        assert harness.repo.call_to( "get_sender_conversations_by_date" ).kwargs[ "include_hidden" ] is True

    def test_an_unparseable_anchor_is_a_400_and_no_query_runs( self, harness ):
        r = harness.client.get( f"{self._URL}?anchor=not-a-timestamp" )
        assert r.status_code == 400
        assert harness.repo.calls == []

    def test_an_empty_history_is_an_empty_dict_and_not_a_404( self, harness ):
        harness.repo.returns( "get_sender_conversations_by_date", {} )
        r = harness.client.get( self._URL )
        assert r.status_code == 200
        assert r.json() == {}

    def test_an_unknown_user_is_a_404( self, harness, user_lookup ):
        user_lookup[ "user" ] = None
        assert harness.client.get( self._URL ).status_code == 404

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_sender_conversations_by_date", RuntimeError( "boom" ) )
        assert harness.client.get( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# DELETE /api/notifications/date/{sender_id}/{user_email}/{date_string}
# ═══════════════════════════════════════════════════════════════════════════════

class TestSoftDeletingADate:

    _URL = f"/api/notifications/date/{_S}/{_EMAIL}/2026-06-15"

    def test_it_hides_and_reports_the_count( self, harness ):
        harness.repo.returns( "soft_delete_by_date", 6 )
        r = harness.client.delete( self._URL )
        assert_no_accidental_500( r )
        body = r.json()
        assert body[ "status" ]       == "success"
        assert body[ "hidden_count" ] == 6
        assert body[ "date" ]         == "2026-06-15"

    def test_this_is_the_SOFT_delete_and_nothing_is_removed( self, harness ):
        """
        🔴 THE WHOLE POINT IS THAT THE DATA SURVIVES. A handler reaching for
        delete_by_sender would return the same shape, the same 200 and the same count,
        and would destroy rows the endpoint promises only to hide.
        """
        harness.repo.returns( "soft_delete_by_date", 1 )
        harness.client.delete( self._URL )
        harness.repo.assert_only_called( "soft_delete_by_date" )
        harness.repo.assert_never_called( "delete_by_sender", "bulk_delete_by_user" )

    def test_the_date_and_the_zone_both_reach_the_query( self, harness ):
        """
        The date alone is ambiguous — "2026-06-15" is a different set of rows in New
        York than in UTC. Both must travel or the wrong day gets hidden.
        """
        harness.set_app_timezone( "America/New_York" )
        harness.repo.returns( "soft_delete_by_date", 0 )
        harness.client.delete( self._URL )
        call = harness.repo.call_to( "soft_delete_by_date" )
        assert call.kwargs[ "date_string" ]   == "2026-06-15"
        assert call.kwargs[ "timezone_name" ] == "America/New_York"
        assert call.kwargs[ "recipient_id" ]  == uuid.UUID( _UID )

    def test_a_malformed_date_is_a_400_before_the_user_is_even_looked_up( self, harness, user_lookup ):
        """
        The date is validated FIRST — cheapest guard first, and it means a bad date
        cannot be reported as a missing user.
        """
        r = harness.client.delete( f"/api/notifications/date/{_S}/{_EMAIL}/15-06-2026" )
        assert r.status_code == 400
        assert user_lookup[ "calls" ] == []
        assert harness.repo.calls     == []

    def test_a_real_but_impossible_date_is_also_a_400( self, harness ):
        """February 30th parses as a shape and not as a date — the guard is fromisoformat."""
        r = harness.client.delete( f"/api/notifications/date/{_S}/{_EMAIL}/2026-02-30" )
        assert r.status_code == 400

    def test_an_unknown_user_is_a_404_and_hides_nothing( self, harness, user_lookup ):
        user_lookup[ "user" ] = None
        r = harness.client.delete( self._URL )
        assert r.status_code == 404
        assert harness.repo.calls == []

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "soft_delete_by_date", RuntimeError( "boom" ) )
        assert harness.client.delete( self._URL ).status_code == 500


# ═══════════════════════════════════════════════════════════════════════════════
# GET /api/notifications/sender-dates/{sender_id}/{user_email}
# ═══════════════════════════════════════════════════════════════════════════════

class TestTheDateSummaries:

    _URL = f"/api/notifications/sender-dates/{_S}/{_EMAIL}"

    def test_it_returns_the_summaries_as_the_whole_body( self, harness ):
        harness.repo.returns( "get_sender_date_summaries",
                              [ { "date": "2026-06-15", "count": 3 } ] )
        r = harness.client.get( self._URL )
        assert_no_accidental_500( r )
        assert r.json() == [ { "date": "2026-06-15", "count": 3 } ]

    def test_the_timezone_name_reaches_the_query( self, harness ):
        harness.set_app_timezone( "America/New_York" )
        harness.repo.returns( "get_sender_date_summaries", [] )
        harness.client.get( self._URL )
        assert harness.repo.call_to( "get_sender_date_summaries" ).kwargs[ "timezone_name" ] == "America/New_York"

    def test_include_hidden_defaults_to_false( self, harness ):
        harness.repo.returns( "get_sender_date_summaries", [] )
        harness.client.get( self._URL )
        assert harness.repo.call_to( "get_sender_date_summaries" ).kwargs[ "include_hidden" ] is False

    def test_include_hidden_true_is_forwarded( self, harness ):
        harness.repo.returns( "get_sender_date_summaries", [] )
        harness.client.get( f"{self._URL}?include_hidden=true" )
        assert harness.repo.call_to( "get_sender_date_summaries" ).kwargs[ "include_hidden" ] is True

    def test_the_summaries_are_scoped_to_sender_and_recipient( self, harness ):
        harness.repo.returns( "get_sender_date_summaries", [] )
        harness.client.get( self._URL )
        call = harness.repo.call_to( "get_sender_date_summaries" )
        assert call.kwargs[ "sender_id" ]    == _SENDER
        assert call.kwargs[ "recipient_id" ] == uuid.UUID( _UID )

    def test_reading_the_summaries_writes_nothing( self, harness ):
        harness.repo.returns( "get_sender_date_summaries", [] )
        harness.client.get( self._URL )
        harness.repo.assert_only_called( "get_sender_date_summaries" )

    def test_an_unknown_user_is_a_404( self, harness, user_lookup ):
        user_lookup[ "user" ] = None
        assert harness.client.get( self._URL ).status_code == 404

    def test_a_repo_fault_is_a_500( self, harness ):
        harness.repo.raises( "get_sender_date_summaries", RuntimeError( "boom" ) )
        assert harness.client.get( self._URL ).status_code == 500
