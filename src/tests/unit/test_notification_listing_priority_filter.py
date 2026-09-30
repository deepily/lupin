"""
GET /api/notifications/{user_id}: the priority filter and oldest-first order (row e25f8868).

THE INCIDENT (Pocholo, reviewing lupin-mobile row 7cac3a17): the queue inserts urgent and
high at the FRONT and appends the rest, and the endpoint slices `[:limit]` in queue order.
A phone that may only show low/medium therefore asked for a page and got a page of
urgent/high it had to throw away, and the low/medium items behind them never arrived. The
mobile stopgap was limit=500.

THE FIX: `priorities=` filters BEFORE the slice, and `sort=oldest` orders by creation time.
Both live in the queue method, where the real NotificationItem objects are; the router
parses, validates and forwards.

The first class drives the incident end to end — HTTP request, router, a REAL
NotificationFifoQueue, the slice — because that is the layer it entered at. A router test
over a stubbed queue could not see the slice eat the page, and a queue test could not see
the router forget to forward the filter.
"""
import sys
from unittest.mock import MagicMock, patch

import pytest

from cosa.rest.routers import notifications as notif
from tests.helpers.notifications_endpoint_harness import a_uuid, make_harness_fixture

harness = make_harness_fixture()

_USER = a_uuid( "priority-filter-user" )


@pytest.fixture
def real_queue():
    """A real NotificationFifoQueue, with the DB log and the timezone lookup stubbed."""
    main = MagicMock()
    main.config_mgr.get.return_value = "America/New_York"
    main.app_debug = False
    pkg  = MagicMock()
    pkg.main = main
    with patch( "cosa.rest.notification_fifo_queue.InputAndOutputTable" ), \
         patch.dict( sys.modules, { "lupin_app": pkg, "lupin_app.main": main } ):
        from cosa.rest.notification_fifo_queue import NotificationFifoQueue
        yield NotificationFifoQueue( websocket_mgr=MagicMock(), emit_enabled=False )


def _push( queue, message, priority, stamp, user=_USER ):
    item = queue.push_notification( message=message, priority=priority, user_id=user )
    item.timestamp = stamp
    return item


# ─── The incident, end to end ───────────────────────────────────────────────────────

class TestThePageIsNoLongerEatenByUrgentItems:

    @pytest.fixture
    def wired( self, harness, real_queue ):
        # Pushed oldest first: two low/medium, then three urgent/high that the queue
        # moves to the FRONT.
        _push( real_queue, "low-1",    "low",    "2026-09-29T09:00:00-04:00" )
        _push( real_queue, "medium-1", "medium", "2026-09-29T09:01:00-04:00" )
        _push( real_queue, "urgent-1", "urgent", "2026-09-29T09:02:00-04:00" )
        _push( real_queue, "high-1",   "high",   "2026-09-29T09:03:00-04:00" )
        _push( real_queue, "urgent-2", "urgent", "2026-09-29T09:04:00-04:00" )
        harness.client.app.dependency_overrides[ notif.get_notification_queue ] = lambda: real_queue
        return harness

    def _messages( self, harness, query ):
        r = harness.client.get( f"/api/notifications/{_USER}?{query}" )
        assert r.status_code == 200, r.text
        return [ n[ "message" ] for n in r.json()[ "notifications" ] ]

    def test_the_control_without_a_filter_the_page_is_all_urgent_and_high( self, wired ):
        """The bug, reproduced: a page of 3 holds none of the allowed items."""
        assert self._messages( wired, "limit=3" ) == [ "urgent-1", "high-1", "urgent-2" ]

    def test_with_the_filter_the_page_holds_the_allowed_items( self, wired ):
        assert self._messages( wired, "limit=3&priorities=low,medium" ) == [ "low-1", "medium-1" ]

    def test_oldest_first_orders_by_creation_not_by_queue_position( self, wired ):
        assert self._messages( wired, "sort=oldest" ) == [
            "low-1", "medium-1", "urgent-1", "high-1", "urgent-2" ]

    def test_filter_and_order_compose_and_the_limit_applies_last( self, wired ):
        assert self._messages( wired, "sort=oldest&priorities=urgent,high&limit=2" ) == [
            "urgent-1", "high-1" ]


# ─── The router: parsing, validation, forwarding ─────────────────────────────────────

class TestTheRouterForwardsAndValidates:

    def _wire( self, harness, items=None ):
        harness.queue.strict().returns( "get_user_notifications", items or [] )

    def _call( self, harness ):
        return harness.queue.call_to( "get_user_notifications" ).kwargs

    def test_without_the_new_parameters_it_forwards_the_old_behaviour( self, harness ):
        self._wire( harness )
        body = harness.client.get( f"/api/notifications/{_USER}" ).json()
        assert self._call( harness )[ "priorities" ] is None
        assert self._call( harness )[ "oldest_first" ] is False
        assert body[ "priorities" ] is None and body[ "sort" ] == "queue"

    @pytest.mark.parametrize( "query", [
        "priorities=low,medium,high",
        "priorities=low&priorities=medium&priorities=high",
        "priorities=low,%20Medium&priorities=HIGH",
        "priorities=low,,medium,&priorities=high",
    ] )
    def test_repeated_comma_separated_and_mixed_case_forms_all_parse( self, harness, query ):
        self._wire( harness )
        body = harness.client.get( f"/api/notifications/{_USER}?{query}" ).json()
        assert self._call( harness )[ "priorities" ] == ( "low", "medium", "high" )
        assert body[ "priorities" ] == [ "low", "medium", "high" ]

    def test_sort_oldest_is_forwarded_as_oldest_first( self, harness ):
        self._wire( harness )
        body = harness.client.get( f"/api/notifications/{_USER}?sort=oldest" ).json()
        assert self._call( harness )[ "oldest_first" ] is True
        assert body[ "sort" ] == "oldest"

    def test_an_unknown_sort_is_a_422( self, harness ):
        self._wire( harness )
        assert harness.client.get( f"/api/notifications/{_USER}?sort=newest" ).status_code == 422

    def test_an_unknown_priority_is_a_400_that_names_it_and_never_reaches_the_queue( self, harness ):
        """
        Refused rather than filtered to nothing. A typo like `normal` would otherwise
        return an empty page, which a client reads as "no notifications".
        """
        self._wire( harness )
        r = harness.client.get( f"/api/notifications/{_USER}?priorities=low,normal" )
        assert r.status_code == 400
        assert "normal" in r.json()[ "detail" ]
        assert harness.queue.calls_to( "get_user_notifications" ) == []

    def test_a_direct_call_uses_real_defaults_not_query_objects( self ):
        """The cosa handler tests call the function directly, without FastAPI."""
        queue = MagicMock()
        queue.get_user_notifications.return_value = []
        import asyncio
        with patch( "cosa.rest.routers.notifications.get_local_timestamp", return_value="t" ):
            asyncio.run( notif.get_user_notifications( user_id=_USER, include_played=True,
                                                       limit=50, notification_queue=queue ) )
        kwargs = queue.get_user_notifications.call_args.kwargs
        assert kwargs[ "priorities" ] is None and kwargs[ "oldest_first" ] is False


# ─── The queue: filter and order ─────────────────────────────────────────────────────

class TestTheQueueFiltersAndOrders:

    def test_the_filter_keeps_only_the_named_priorities( self, real_queue ):
        _push( real_queue, "u", "urgent", "2026-09-29T09:00:00-04:00" )
        _push( real_queue, "l", "low",    "2026-09-29T09:01:00-04:00" )
        got = real_queue.get_user_notifications( _USER, priorities=( "low", ) )
        assert [ n.message for n in got ] == [ "l" ]

    def test_the_filter_and_the_played_filter_both_apply( self, real_queue ):
        played = _push( real_queue, "played-low", "low", "2026-09-29T09:00:00-04:00" )
        played.played = True
        _push( real_queue, "fresh-low", "low", "2026-09-29T09:01:00-04:00" )
        got = real_queue.get_user_notifications( _USER, include_played=False, priorities=( "low", ) )
        assert [ n.message for n in got ] == [ "fresh-low" ]

    def test_another_users_items_never_appear( self, real_queue ):
        _push( real_queue, "theirs", "low", "2026-09-29T09:00:00-04:00", user="someone-else" )
        assert real_queue.get_user_notifications( _USER, priorities=( "low", ) ) == []

    def test_oldest_first_compares_instants_not_text( self, real_queue ):
        """
        13:30 UTC is 09:30 EDT, so it is OLDER than 10:00 EDT — and it sorts AFTER it as
        text. A string sort would put these the wrong way round.
        """
        _push( real_queue, "ten-edt",       "low", "2026-09-29T10:00:00-04:00" )
        _push( real_queue, "nine-thirty",   "low", "2026-09-29T13:30:00+00:00" )
        got = real_queue.get_user_notifications( _USER, oldest_first=True )
        assert [ n.message for n in got ] == [ "nine-thirty", "ten-edt" ]

    def test_equal_stamps_keep_queue_order( self, real_queue ):
        _push( real_queue, "low-first",   "low",    "2026-09-29T10:00:00-04:00" )
        _push( real_queue, "urgent-same", "urgent", "2026-09-29T10:00:00-04:00" )
        got = real_queue.get_user_notifications( _USER, oldest_first=True )
        assert [ n.message for n in got ] == [ "urgent-same", "low-first" ]

    def test_queue_order_is_kept_when_not_asked_to_sort( self, real_queue ):
        _push( real_queue, "low-old",    "low",    "2026-09-29T08:00:00-04:00" )
        _push( real_queue, "urgent-new", "urgent", "2026-09-29T11:00:00-04:00" )
        got = real_queue.get_user_notifications( _USER )
        assert [ n.message for n in got ] == [ "urgent-new", "low-old" ]


class TestTheCreationKeyNeverRaises:

    def _key( self, stamp ):
        from cosa.rest.notification_fifo_queue import _creation_key
        return _creation_key( MagicMock( timestamp=stamp ) )

    def test_an_aware_stamp_is_its_instant( self ):
        assert self._key( "2026-09-29T13:30:00+00:00" ) == self._key( "2026-09-29T09:30:00-04:00" )

    def test_a_naive_stamp_is_read_as_utc( self ):
        assert self._key( "2026-09-29T13:30:00" ) == self._key( "2026-09-29T13:30:00+00:00" )

    @pytest.mark.parametrize( "stamp", [ "not a time", None, "" ] )
    def test_an_unparseable_stamp_sorts_last( self, stamp ):
        assert self._key( stamp ) == float( "inf" )
