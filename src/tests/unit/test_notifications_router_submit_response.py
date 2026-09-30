"""
Unit tests for `_submit_response_sync` in `cosa.rest.routers.notifications`.

This is the ask-answer write path: read the row, refuse it for three distinct reasons,
wrap a bare string, persist, and hand four fields back for the WebSocket broadcast.

🔴 THE THREE REFUSALS ALL RAISE HTTPException, AND TWO OF THEM SHARE A STATUS CODE.
"already responded" and "grace period exceeded" are both 400, so a test asserting only
`pytest.raises( HTTPException )` — or even only the status — cannot tell them apart, and
a handler that collapsed the two would pass. Every refusal here is asserted on its
DETAIL as well as its code.

🔴 THE FOUR RETURNED FIELDS CARRY FOUR DIFFERENT VALUES, for the same reason the
projector tests do: a return dict built from the wrong attribute is invisible against a
row whose fields are equal.

🔴 THE GRACE BOUNDARY IS `>`, NOT `>=`. Exactly-at-the-limit must be ACCEPTED, so both
sides of the comparison are posed — a test only one second past the line accepts an
off-by-one that rejects an answer arriving exactly on time.
"""

import sys
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

# Bootstrap imports
lupin_root = os.environ.get( "LUPIN_ROOT" )
if lupin_root:
    src_path = os.path.join( lupin_root, "src" )
    if src_path not in sys.path:
        sys.path.insert( 0, src_path )

from fastapi import HTTPException

import cosa.rest.routers.notifications as notif


_NID          = "11111111-2222-3333-4444-555555555555"
_GRACE        = 300


class _Row:
    """A Notification row whose four handed-back fields are all DIFFERENT."""

    def __init__( self, state="delivered", expires_at=None ):
        self.state          = state
        self.expires_at     = expires_at
        self.recipient_id   = "RECIPIENT-VALUE"
        self.job_id         = "JOB-VALUE"
        self.sender_id      = "SENDER-VALUE"
        self.sender_persona = "PERSONA-VALUE"


class _Repo:
    def __init__( self, row, updated=True ):
        self._row     = row
        self._updated = updated
        self.updates  = []

    def get_by_id( self, _nid ):
        return self._row

    def update_response( self, nid, response_dict ):
        self.updates.append( ( nid, response_dict ) )
        return self._updated


@pytest.fixture
def wire( monkeypatch ):
    """
    Point the helper at a controllable repo and grace-period config.

    Ensures:
        - returns a callable taking ( row, updated=, grace= ) and yielding the repo
    """
    import lupin_app.main as main_module

    class _Ctx:
        def __enter__( self ):
            return object()
        def __exit__( self, *exc ):
            return False

    def _install( row, updated=True, grace=_GRACE ):
        repo = _Repo( row, updated )

        class _Cfg:
            def get( self, key, default=None, **_kw ):
                if key == "notification grace period seconds":
                    return grace
                return default

        monkeypatch.setattr( notif, "get_db", lambda: _Ctx() )
        monkeypatch.setattr( notif, "NotificationRepository", lambda _s: repo )
        monkeypatch.setattr( main_module, "config_mgr", _Cfg() )
        return repo

    return _install


class TestTheThreeRefusals:
    """
    🔴 TWO OF THESE SHARE A STATUS CODE. Asserting the code alone cannot separate
    "already responded" from "grace exceeded", so each names its own detail text.
    """

    def test_a_missing_row_is_a_404_naming_the_id( self, wire ):
        wire( None )
        with pytest.raises( HTTPException ) as exc:
            notif._submit_response_sync( _NID, "yes" )
        assert exc.value.status_code == 404
        assert _NID in exc.value.detail

    def test_an_already_responded_row_is_a_400_saying_so( self, wire ):
        wire( _Row( state="responded" ) )
        with pytest.raises( HTTPException ) as exc:
            notif._submit_response_sync( _NID, "yes" )
        assert exc.value.status_code == 400
        assert "already responded" in exc.value.detail.lower()

    def test_a_stale_expiry_is_a_400_that_says_GRACE_not_already_responded( self, wire ):
        # 🔴 the discriminating half: same code as the case above, different reason.
        long_ago = datetime.now( timezone.utc ) - timedelta( seconds=_GRACE + 60 )
        wire( _Row( state="expired", expires_at=long_ago ) )
        with pytest.raises( HTTPException ) as exc:
            notif._submit_response_sync( _NID, "yes" )
        assert exc.value.status_code == 400
        assert "grace" in exc.value.detail.lower()
        assert "already responded" not in exc.value.detail.lower()

    def test_a_failed_update_is_a_500( self, wire ):
        wire( _Row(), updated=False )
        with pytest.raises( HTTPException ) as exc:
            notif._submit_response_sync( _NID, "yes" )
        assert exc.value.status_code == 500


class TestTheGraceBoundary:
    """
    The comparison is `> grace_period_seconds`, so exactly-at-the-limit is ACCEPTED.
    Both sides are posed; a test only well past the line accepts an off-by-one that
    rejects an answer arriving exactly on time.
    """

    def test_an_answer_arriving_EXACTLY_on_the_limit_is_accepted( self, wire, monkeypatch ):
        """
        🔴 THE ONLY CASE THAT PINS `>` RATHER THAN `>=`, AND MY FIRST CUT DID NOT HAVE
        IT. A mutation flipping the comparison SURVIVED a file whose own docstring
        claimed both sides were posed: "60 seconds inside" and "60 seconds outside"
        both give the same verdict under either operator. Only elapsed == grace
        separates them, and a real clock cannot land there — so the clock is frozen.

        Ensures:
            - elapsed exactly equal to the grace window is ACCEPTED, not refused
        """
        fixed = datetime( 2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc )

        class _Clock( datetime ):
            @classmethod
            def now( cls, tz=None ):
                return fixed

        monkeypatch.setattr( notif, "datetime", _Clock )
        wire( _Row( state="expired", expires_at=fixed - timedelta( seconds=_GRACE ) ) )
        out = notif._submit_response_sync( _NID, "yes" )
        assert out[ "recipient_id" ] == "RECIPIENT-VALUE"

    def test_one_second_past_the_limit_is_refused( self, wire, monkeypatch ):
        """
        The other half of the same frozen-clock pair. Together these two are the
        smallest interval that distinguishes `>` from `>=` — and from `<`.
        """
        fixed = datetime( 2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc )

        class _Clock( datetime ):
            @classmethod
            def now( cls, tz=None ):
                return fixed

        monkeypatch.setattr( notif, "datetime", _Clock )
        wire( _Row( state="expired", expires_at=fixed - timedelta( seconds=_GRACE + 1 ) ) )
        with pytest.raises( HTTPException ) as exc:
            notif._submit_response_sync( _NID, "yes" )
        assert exc.value.status_code == 400
        assert "grace" in exc.value.detail.lower()

    def test_an_expired_row_inside_the_grace_period_is_accepted( self, wire ):
        recent = datetime.now( timezone.utc ) - timedelta( seconds=_GRACE - 60 )
        wire( _Row( state="expired", expires_at=recent ) )
        out = notif._submit_response_sync( _NID, "yes" )
        assert out[ "recipient_id" ] == "RECIPIENT-VALUE"

    def test_an_expired_row_with_no_expires_at_is_accepted( self, wire ):
        # 🔴 the `expires_at and ...` guard. Without this case a helper that dropped
        # the None check raises TypeError on a row the design says to accept.
        wire( _Row( state="expired", expires_at=None ) )
        out = notif._submit_response_sync( _NID, "yes" )
        assert out[ "job_id" ] == "JOB-VALUE"

    def test_an_expired_row_well_past_the_grace_period_is_refused( self, wire ):
        long_ago = datetime.now( timezone.utc ) - timedelta( seconds=_GRACE + 600 )
        wire( _Row( state="expired", expires_at=long_ago ) )
        with pytest.raises( HTTPException ):
            notif._submit_response_sync( _NID, "yes" )

    def test_the_grace_window_is_read_from_config_not_hard_coded( self, wire ):
        """
        🔴 THE CONFIGURED VALUE IS NOT THE DEFAULT. With grace=300 in the fixture, a
        hard-coded 300 is indistinguishable from reading the config. This uses 1000,
        and an age of 500s — refused under the default, ACCEPTED under the config.
        """
        aged = datetime.now( timezone.utc ) - timedelta( seconds=500 )
        wire( _Row( state="expired", expires_at=aged ), grace=1000 )
        out = notif._submit_response_sync( _NID, "yes" )
        assert out[ "sender_id" ] == "SENDER-VALUE"


class TestTheResponseWrapping:

    def test_a_bare_string_is_wrapped_with_its_source( self, wire ):
        repo = wire( _Row() )
        notif._submit_response_sync( _NID, "yes" )
        _nid, payload = repo.updates[ 0 ]
        assert payload == { "value": "yes", "source": "ui" }

    def test_a_dict_is_passed_through_unwrapped( self, wire ):
        """
        🔴 THE DICT ALREADY HAS A 'value' KEY, so a helper that wrapped it anyway
        produces {"value": {...}} — a different shape, not an equal one.
        """
        repo = wire( _Row() )
        given = { "value": "no", "source": "cli", "extra": 1 }
        notif._submit_response_sync( _NID, given )
        _nid, payload = repo.updates[ 0 ]
        assert payload == given

    def test_the_update_is_keyed_by_a_uuid_not_the_raw_string( self, wire ):
        repo = wire( _Row() )
        notif._submit_response_sync( _NID, "yes" )
        nid, _payload = repo.updates[ 0 ]
        assert nid == uuid.UUID( _NID )
        assert isinstance( nid, uuid.UUID )


class TestTheHandback:

    def test_all_four_fields_come_back_under_their_own_keys( self, wire ):
        # 🔴 four DIFFERENT values, so a dict built from the wrong attribute is visible.
        wire( _Row() )
        out = notif._submit_response_sync( _NID, "yes" )
        assert out == {
            "recipient_id"   : "RECIPIENT-VALUE",
            "job_id"         : "JOB-VALUE",
            "sender_id"      : "SENDER-VALUE",
            "sender_persona" : "PERSONA-VALUE",
        }

    def test_the_recipient_id_is_stringified( self, wire ):
        class _Weird:
            def __str__( self ):
                return "the-stringified-recipient"
        row = _Row()
        row.recipient_id = _Weird()
        wire( row )
        out = notif._submit_response_sync( _NID, "yes" )
        assert out[ "recipient_id" ] == "the-stringified-recipient"
        assert isinstance( out[ "recipient_id" ], str )

    def test_it_is_a_dict_not_the_old_two_tuple( self, wire ):
        # the §4.3 shape change, pinned: a tuple would unpack silently at some call
        # sites and lose the two routing keys at the rest.
        wire( _Row() )
        out = notif._submit_response_sync( _NID, "yes" )
        assert isinstance( out, dict )
