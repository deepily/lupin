"""
Unit tests for the synchronous DB helpers in `cosa.rest.routers.notifications`.

These five are thin wrappers that each open a session, build a repository and call
ONE repo method. That shape has a specific failure mode worth naming: a wrapper that
calls the WRONG repo method still opens a session, still coerces its UUID, and still
returns None — so a test asserting only "it ran" or "the repo was touched" passes
every one of them equally.

🔴 SO EVERY TEST HERE ASSERTS THREE THINGS: the right method was called, with the
right argument, AND no other repo method was called at all. The third is the one that
catches a crossed wrapper, and it is the one a coverage number rewards you for
omitting.

The UUID coercion is asserted by TYPE, not by value: `uuid.UUID( s )` and `s` compare
unequal but a lenient repo mock accepts either, so passing the raw string through is
invisible unless the type is checked.
"""

import sys
import os
import uuid

import pytest

# Bootstrap imports
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

import cosa.rest.routers.notifications as notif


# Every repo method the five wrappers might reach for. A test asserts the one it
# expects fired and that every OTHER name here stayed untouched.
_REPO_METHODS = (
    "update_state", "mark_expired", "mark_answer_delivered", "get_by_id",
)


class _Repo:
    """Records which methods were called with what, and answers get_by_id."""

    def __init__( self, row=None ):
        self.calls = []
        self._row  = row

    def __getattr__( self, name ):
        if name.startswith( "_" ):
            raise AttributeError( name )
        def recorder( *args, **kwargs ):
            self.calls.append( ( name, args, kwargs ) )
            return self._row if name == "get_by_id" else None
        return recorder

    def names( self ):
        return [ name for name, _a, _k in self.calls ]


class _Session:
    pass


@pytest.fixture
def repo_spy( monkeypatch ):
    """
    Replace get_db() and NotificationRepository so the wrappers run against a spy.

    Ensures:
        - the session yielded by the context manager is the one handed to the repo
        - the spy records every repo call in order
    """
    session = _Session()
    holder  = {}

    class _Ctx:
        def __enter__( self ):
            return session
        def __exit__( self, *exc ):
            return False

    def _repo_factory( given_session ):
        holder[ "session" ] = given_session
        return holder[ "repo" ]

    holder[ "repo" ]    = _Repo()
    holder[ "session" ] = None
    monkeypatch.setattr( notif, "get_db", lambda: _Ctx() )
    monkeypatch.setattr( notif, "NotificationRepository", _repo_factory )
    holder[ "expected_session" ] = session
    return holder


def _only_call( holder, expected_name ):
    """
    Assert exactly one repo method fired and it was `expected_name`.

    🔴 THE 'AND NOTHING ELSE' HALF IS THE POINT. A wrapper calling the wrong method
    satisfies any assertion that only looks at the method it was supposed to call
    — because that one simply reads as never-called on a lenient mock.
    """
    repo = holder[ "repo" ]
    assert repo.names() == [ expected_name ], (
        f"expected exactly one repo call to {expected_name!r}, got {repo.names()!r}" )
    for other in _REPO_METHODS:
        if other != expected_name:
            assert other not in repo.names()
    return repo.calls[ 0 ]


class TestUpdateNotificationStateSync:

    def test_it_updates_state_on_the_right_row_and_nothing_else( self, repo_spy ):
        nid = "11111111-2222-3333-4444-555555555555"
        notif._update_notification_state_sync( nid, "delivered" )
        _name, args, _kwargs = _only_call( repo_spy, "update_state" )
        assert args == ( uuid.UUID( nid ), "delivered" )

    def test_the_id_is_coerced_to_a_uuid_not_passed_as_a_string( self, repo_spy ):
        # 🔴 TYPE, NOT VALUE. A lenient repo takes either, so only the type tells them
        # apart — and a real repo keyed on a str would silently match nothing.
        nid = "11111111-2222-3333-4444-555555555555"
        notif._update_notification_state_sync( nid, "delivered" )
        _name, args, _kwargs = repo_spy[ "repo" ].calls[ 0 ]
        assert isinstance( args[ 0 ], uuid.UUID )

    def test_the_state_is_not_crossed_with_the_id( self, repo_spy ):
        # the two arguments are of different types AND different values, so any swap
        # is visible rather than merely improbable.
        nid = "11111111-2222-3333-4444-555555555555"
        notif._update_notification_state_sync( nid, "expired" )
        _name, args, _kwargs = repo_spy[ "repo" ].calls[ 0 ]
        assert args[ 1 ] == "expired"

    def test_the_repo_is_built_on_the_session_the_context_manager_yielded( self, repo_spy ):
        notif._update_notification_state_sync( "11111111-2222-3333-4444-555555555555", "x" )
        assert repo_spy[ "session" ] is repo_spy[ "expected_session" ]

    def test_a_repo_error_propagates_rather_than_being_swallowed( self, repo_spy, monkeypatch ):
        """
        The docstring promises the caller handles it. A wrapper that caught and
        returned None would leave the caller believing the write landed.
        """
        class _Boom:
            def update_state( self, *_a, **_k ):
                raise RuntimeError( "db is down" )
        monkeypatch.setattr( notif, "NotificationRepository", lambda _s: _Boom() )
        with pytest.raises( RuntimeError, match="db is down" ):
            notif._update_notification_state_sync( "11111111-2222-3333-4444-555555555555", "x" )


class TestMarkNotificationExpiredSync:

    def test_it_marks_expired_on_the_right_row_and_nothing_else( self, repo_spy ):
        nid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        notif._mark_notification_expired_sync( nid )
        _name, args, _kwargs = _only_call( repo_spy, "mark_expired" )
        assert args == ( uuid.UUID( nid ), )

    def test_a_repo_error_propagates( self, repo_spy, monkeypatch ):
        class _Boom:
            def mark_expired( self, *_a, **_k ):
                raise RuntimeError( "db is down" )
        monkeypatch.setattr( notif, "NotificationRepository", lambda _s: _Boom() )
        with pytest.raises( RuntimeError ):
            notif._mark_notification_expired_sync( "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee" )


class TestMarkAnswerDeliveredSync:

    def test_it_stamps_answer_delivered_and_nothing_else( self, repo_spy ):
        """
        🔴 THIS ONE MUST NOT BE mark_expired. Both take a single UUID and return
        None, so they are interchangeable to any test that does not name the method
        — and stamping "expired" where "delivered" belongs loses a human's answer.
        """
        nid = "99999999-8888-7777-6666-555555555555"
        notif._mark_answer_delivered_sync( nid )
        _name, args, _kwargs = _only_call( repo_spy, "mark_answer_delivered" )
        assert args == ( uuid.UUID( nid ), )

    def test_it_never_deletes_the_row( self, repo_spy ):
        # the docstring's promise, asserted: no destructive method is reached for.
        notif._mark_answer_delivered_sync( "99999999-8888-7777-6666-555555555555" )
        assert not any( "delete" in name for name in repo_spy[ "repo" ].names() )


class TestReadNotificationStateSync:
    """
    Read {state, response_value, responded_at} for the ask re-attach poll.

    🔴 THE THREE FIELDS CARRY THREE DIFFERENT VALUES. A reader that returned the
    same attribute three times, or crossed two of them, is invisible against a row
    whose fields are equal.
    """

    def test_a_missing_row_reads_as_none( self, repo_spy ):
        repo_spy[ "repo" ]._row = None
        out = notif._read_notification_state_sync( "11111111-2222-3333-4444-555555555555" )
        assert out is None

    def test_it_returns_the_three_fields_under_their_own_keys( self, repo_spy ):
        class _Row:
            state          = "STATE-VALUE"
            response_value = "RESPONSE-VALUE"
            responded_at   = "RESPONDED-VALUE"
        repo_spy[ "repo" ]._row = _Row()
        out = notif._read_notification_state_sync( "11111111-2222-3333-4444-555555555555" )
        assert out == {
            "state"          : "STATE-VALUE",
            "response_value" : "RESPONSE-VALUE",
            "responded_at"   : "RESPONDED-VALUE",
        }

    def test_responded_at_is_returned_raw_not_isoformatted( self, repo_spy ):
        """
        The docstring promises a datetime|None verbatim — the SSE generator tests it
        for None-ness, so a string here would read as "answered" forever.
        """
        class _Row:
            state          = "s"
            response_value = None
            responded_at   = None
        repo_spy[ "repo" ]._row = _Row()
        out = notif._read_notification_state_sync( "11111111-2222-3333-4444-555555555555" )
        assert out[ "responded_at" ]   is None
        assert out[ "response_value" ] is None

    def test_the_lookup_uses_a_uuid_and_only_get_by_id( self, repo_spy ):
        nid = "11111111-2222-3333-4444-555555555555"
        repo_spy[ "repo" ]._row = None
        notif._read_notification_state_sync( nid )
        _name, args, _kwargs = _only_call( repo_spy, "get_by_id" )
        assert args == ( uuid.UUID( nid ), )

    def test_a_uuid_object_is_accepted_as_well_as_a_string( self, repo_spy ):
        # the helper wraps its argument in uuid.UUID( str( ... ) ), so a UUID in is
        # the same UUID out rather than a TypeError.
        nid = uuid.UUID( "11111111-2222-3333-4444-555555555555" )
        repo_spy[ "repo" ]._row = None
        notif._read_notification_state_sync( nid )
        _name, args, _kwargs = repo_spy[ "repo" ].calls[ 0 ]
        assert args == ( nid, )
