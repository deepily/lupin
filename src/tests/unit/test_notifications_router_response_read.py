"""
Unit tests for GET /api/notifications/response/{id} — the re-attach poll target.

🔴 THE LOAD-BEARING CLAIM IS A NEGATIVE ONE. The docstring calls this a PURE READ:
serving an answer is not a receipt, so the endpoint must never stamp
`answer_delivered_at`. A negative claim is exactly what a coverage number rewards you
for not testing — the lines run either way — so it is asserted directly here, by
proving the repo's receipt setter is never reached.

🔴 AND THE 404 MUST NOT ARRIVE AS A 500. The handler wraps everything in a try/except
that converts stray exceptions to 500, with an `except HTTPException: raise` ahead of
it. Delete that one clause and a missing notification becomes a server error — the
caller then retries a row that will never exist. The test asserts the CODE, so the two
outcomes are distinguishable.
"""

import sys
import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Bootstrap imports
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

import cosa.rest.routers.notifications as notif
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt


_NID = "11111111-2222-3333-4444-555555555555"


class _Stamp:
    def __init__( self, text ):
        self._text = text
    def isoformat( self ):
        return self._text


class _Row:
    """Three DIFFERENT values, so a handler reading the wrong attribute is visible."""
    state          = "STATE-VALUE"
    response_value = "RESPONSE-VALUE"
    responded_at   = _Stamp( "RESPONDED-VALUE" )


class _Repo:
    def __init__( self, row ):
        self._row  = row
        self.calls = []

    def get_by_id( self, nid ):
        self.calls.append( ( "get_by_id", nid ) )
        return self._row

    def __getattr__( self, name ):
        if name.startswith( "_" ):
            raise AttributeError( name )
        def recorder( *args, **_kw ):
            self.calls.append( ( name, args[ 0 ] if args else None ) )
            return None
        return recorder


@pytest.fixture
def client( monkeypatch ):
    """
    A TestClient over the notifications router with auth stubbed and the repo spied.

    Ensures:
        - returns ( client, install ) where install( row ) wires a repo and hands it back
    """
    app = FastAPI()
    app.include_router( notif.router )
    app.dependency_overrides[ require_api_key_or_jwt ] = lambda: "test-user"

    # the success envelope calls get_local_timestamp(), which reads lupin_app.main's
    # config — unset in a unit context, so it is stubbed rather than left to explode
    # and turn every 200 into a 500.
    import lupin_app.main as main_module

    class _Cfg:
        def get( self, _key, default=None, **_kw ):
            return default

    monkeypatch.setattr( main_module, "config_mgr", _Cfg() )
    monkeypatch.setattr( main_module, "app_debug", False, raising=False )

    holder = {}

    class _Ctx:
        def __enter__( self ):
            return object()
        def __exit__( self, *exc ):
            return False

    def install( row ):
        repo = _Repo( row )
        holder[ "repo" ] = repo
        monkeypatch.setattr( notif, "get_db", lambda: _Ctx() )
        monkeypatch.setattr( notif, "NotificationRepository", lambda _s: repo )
        return repo

    with TestClient( app ) as c:
        yield c, install

    app.dependency_overrides.clear()


class TestTheHappyRead:

    def test_it_returns_the_three_fields_under_their_own_keys( self, client ):
        c, install = client
        install( _Row() )
        body = c.get( f"/api/notifications/response/{_NID}" ).json()
        assert body[ "state" ]          == "STATE-VALUE"
        assert body[ "response_value" ] == "RESPONSE-VALUE"
        assert body[ "responded_at" ]   == "RESPONDED-VALUE"

    def test_it_echoes_the_id_it_was_asked_about( self, client ):
        c, install = client
        install( _Row() )
        body = c.get( f"/api/notifications/response/{_NID}" ).json()
        assert body[ "notification_id" ] == _NID
        assert body[ "status" ]          == "success"

    def test_an_unanswered_row_reports_responded_at_as_none( self, client ):
        """
        🔴 THE CALLER DECIDES LANDED-NESS ON `responded_at IS NOT NULL`. A handler
        that emitted "" or "None" here would read as ANSWERED forever, so the JSON
        null is asserted rather than falsiness.
        """
        class _Unanswered( _Row ):
            responded_at = None
        c, install = client
        install( _Unanswered() )
        body = c.get( f"/api/notifications/response/{_NID}" ).json()
        assert body[ "responded_at" ] is None

    def test_the_lookup_is_keyed_by_a_uuid( self, client ):
        c, install = client
        repo = install( _Row() )
        c.get( f"/api/notifications/response/{_NID}" )
        name, arg = repo.calls[ 0 ]
        assert name == "get_by_id"
        assert arg  == uuid.UUID( _NID )


class TestItIsAPureRead:
    """
    🔴 THE NEGATIVE CLAIM, ASSERTED. Serving is not a receipt — §4.5 E-b. Nothing here
    may stamp answer_delivered_at, and the lines of this handler run identically
    whether it does or not, so only an explicit assertion catches it.
    """

    def test_serving_an_answer_never_stamps_the_receipt( self, client ):
        c, install = client
        repo = install( _Row() )
        c.get( f"/api/notifications/response/{_NID}" )
        called = [ name for name, _arg in repo.calls ]
        assert called == [ "get_by_id" ], (
            f"a pure read must touch only get_by_id, but reached {called!r} — serving "
            "an answer is not a receipt" )

    def test_it_writes_nothing_at_all( self, client ):
        c, install = client
        repo = install( _Row() )
        c.get( f"/api/notifications/response/{_NID}" )
        for writer in ( "mark_answer_delivered", "update_state", "update_response",
                        "mark_expired" ):
            assert writer not in [ name for name, _a in repo.calls ]


class TestTheRefusals:

    def test_a_missing_row_is_a_404_and_not_a_500( self, client ):
        """
        🔴 THE CODE IS THE ASSERTION. The handler's blanket `except Exception` turns
        anything it catches into a 500, and only the `except HTTPException: raise`
        clause ahead of it keeps this a 404. Both are error responses, so asserting
        "it failed" cannot tell them apart — and they mean opposite things to a
        caller deciding whether to retry.
        """
        c, install = client
        install( None )
        r = c.get( f"/api/notifications/response/{_NID}" )
        assert r.status_code == 404
        assert _NID in r.json()[ "detail" ]

    def test_a_repo_explosion_is_a_500_not_a_404( self, client ):
        # the other side of the same fork: a genuine fault must NOT masquerade as
        # "no such notification", or the caller stops retrying something transient.
        c, install = client

        class _Boom:
            def get_by_id( self, _nid ):
                raise RuntimeError( "connection reset" )

        repo = install( _Row() )
        import cosa.rest.routers.notifications as _n
        _n.NotificationRepository = lambda _s: _Boom()
        r = c.get( f"/api/notifications/response/{_NID}" )
        assert r.status_code == 500
