"""
Unit tests for the `user_filter` arm of GET /api/job-history (bug e205a3b1).

THE DEFECT THESE PIN. The endpoint had no `user_filter` parameter at all, and FastAPI
drops an unknown query parameter silently — so `?user_filter=*` returned 200 with the
caller's OWN rows and `filtered_by` still pinned to their uid. The sibling endpoint
`/api/get-queue/{queue_name}` refuses the identical request with a 403 naming the admin
rule. Same permission model, two ways of saying no: one honest, one that hands the
caller a partial view they believe is complete.

MEASURED 2026-08-17: two seats read the same `:8000` queue and reported opposite
answers — one saw two scheduled jobs, one saw none — because the rows belonged to a
different account and nothing in the response said so. The widening flag was passed and
ignored. That reading was relayed onward as established fact before it was caught.

PROOF BY DELETION. Every assertion here goes red when the `user_filter` arm is removed
from `get_job_history`:
  · delete the parameter → the four 403 tests error on an unexpected keyword
  · keep the parameter but drop the `authorize_queue_filter` call → the four 403 tests
    fail, because a non-admin is silently answered instead of refused
  · drop the `!self` arm → test_admin_not_self_is_REFUSED_rather_than_answered_wrongly
    fails, because "!uid" reaches an equality filter and matches nothing

Generated on: 2026-08-17
"""

import asyncio
import unittest
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from cosa.rest.routers.queues import get_job_history


REGULAR = { "uid" : "user_931e9dae", "roles" : [ "user" ] }
ADMIN   = { "uid" : "admin_0001",    "roles" : [ "admin" ] }

# The other account from the incident — the one whose rows a regular seat cannot see.
OTHER_UID = "user_50c73ba7"


def _call( current_user, user_filter=None, capture=None ):
    """
    Drive the handler directly with every dependency supplied explicitly.

    `query_job_history` is patched so these tests never touch PostgreSQL; `capture`
    receives the kwargs it was called with, which is how the tests assert WHICH rows
    were asked for rather than only what came back.
    """
    def _fake_query( **kwargs ):
        if capture is not None: capture.update( kwargs )
        return { "jobs" : [], "total" : 0 }

    with patch( "cosa.rest.job_persistence.query_job_history", _fake_query ):
        return asyncio.run( get_job_history(
            current_user = current_user,
            status       = None,
            job_type     = None,
            limit        = 20,
            offset       = 0,
            days         = None,
            exclude_ids  = None,
            user_filter  = user_filter
        ) )


class TestJobHistoryRefusesWhatItCannotGrant( unittest.TestCase ):
    """A filter the caller is not entitled to must be REFUSED, never quietly narrowed."""

    def test_regular_user_asking_for_ALL_gets_403_not_a_narrowed_200( self ):
        """
        🔴 THE HEADLINE. This exact call returned 200 with 14 self-filtered rows before
        the fix, which is how a seat concluded another account's jobs did not exist.
        """
        with pytest.raises( HTTPException ) as exc:
            _call( REGULAR, user_filter="*" )

        assert exc.value.status_code == 403
        assert "admin" in exc.value.detail.lower()

    def test_regular_user_asking_for_ANOTHER_account_gets_403( self ):
        """The incident's shape: a seat asking about the account that owned the rows."""
        with pytest.raises( HTTPException ) as exc:
            _call( REGULAR, user_filter=OTHER_UID )

        assert exc.value.status_code == 403

    def test_regular_user_asking_for_NOT_SELF_gets_403( self ):
        """The third vocabulary word the sibling endpoint accepts, refused the same way."""
        with pytest.raises( HTTPException ) as exc:
            _call( REGULAR, user_filter="!self" )

        assert exc.value.status_code == 403

    def test_the_refusal_matches_the_sibling_endpoint_word_for_word( self ):
        """
        Same permission model must produce the same refusal. If these two ever drift
        apart again, one of them is teaching callers something the other denies.
        """
        from cosa.rest.queue_auth import authorize_queue_filter

        with pytest.raises( HTTPException ) as sibling:
            authorize_queue_filter( REGULAR, "*" )
        with pytest.raises( HTTPException ) as history:
            _call( REGULAR, user_filter="*" )

        assert history.value.status_code == sibling.value.status_code
        assert history.value.detail      == sibling.value.detail


class TestJobHistoryHonoursWhatItCanGrant( unittest.TestCase ):
    """The entitled cases still work, and ask the store for the right rows."""

    def test_admin_asking_for_ALL_queries_every_user( self ):
        capture = { }
        body    = _call( ADMIN, user_filter="*", capture=capture )

        assert capture[ "user_id" ] is None          # no equality filter → every row
        assert body[ "filtered_by" ] == "all"

    def test_admin_asking_for_a_SPECIFIC_account_queries_that_account( self ):
        """
        The call that would have settled the incident in one request: an admin asking
        about the account that actually owned the rows.
        """
        capture = { }
        body    = _call( ADMIN, user_filter=OTHER_UID, capture=capture )

        assert capture[ "user_id" ]  == OTHER_UID
        assert body[ "filtered_by" ] == OTHER_UID

    def test_regular_user_asking_for_THEMSELVES_is_allowed( self ):
        capture = { }
        body    = _call( REGULAR, user_filter=REGULAR[ "uid" ], capture=capture )

        assert capture[ "user_id" ]  == REGULAR[ "uid" ]
        assert body[ "filtered_by" ] == REGULAR[ "uid" ]

    def test_admin_not_self_is_REFUSED_rather_than_answered_wrongly( self ):
        """
        ⚠️ ACCEPTED LIMIT, asserted so it stays a decision. `authorize_queue_filter`
        grants an admin the "!self" filter, but `query_job_history` filters on user_id
        EQUALITY — there is no exclusion arm to hand "!uid" to. Passing it through
        would match zero rows and read as "no such jobs", which is the exact failure
        this endpoint was just fixed for. So it 400s instead.

        If this goes red because exclusion got implemented, that is a change to state,
        not a failure to fix.
        """
        with pytest.raises( HTTPException ) as exc:
            _call( ADMIN, user_filter="!self" )

        assert exc.value.status_code == 400
        assert "not supported" in exc.value.detail.lower()


class TestTheDefaultViewIsUnchanged( unittest.TestCase ):
    """
    The fix must not move behaviour for the callers who never pass the flag — the UI
    among them. Omitting `user_filter` has to mean exactly what it meant before.
    """

    def test_regular_user_with_no_filter_still_sees_only_their_own( self ):
        capture = { }
        body    = _call( REGULAR, capture=capture )

        assert capture[ "user_id" ]  == REGULAR[ "uid" ]
        assert body[ "filtered_by" ] == REGULAR[ "uid" ]

    def test_admin_with_no_filter_still_sees_everything( self ):
        capture = { }
        body    = _call( ADMIN, capture=capture )

        assert capture[ "user_id" ] is None
        assert body[ "filtered_by" ] == "all"

    def test_the_response_shape_is_unchanged( self ):
        body = _call( REGULAR )

        assert set( body.keys() ) == { "jobs", "total", "filtered_by", "limit", "offset" }


class TestTheIncidentItself( unittest.TestCase ):
    """
    The scenario end to end, since a fix checked only from the entitled side looks fine
    and changes nothing for the reader it misleads.
    """

    def test_a_regular_seat_can_no_longer_believe_it_saw_the_whole_queue( self ):
        """
        Account A submits; account B reads with the widening flag. Before the fix B got
        200 and its own rows, and concluded A's jobs did not exist. Now B is told no.
        """
        rows_owned_by_a = { "jobs" : [ { "id_hash" : "ts-1e2a1cb8", "user_id" : OTHER_UID } ],
                            "total" : 1 }

        with patch( "cosa.rest.job_persistence.query_job_history",
                    lambda **kw: rows_owned_by_a if kw.get( "user_id" ) in ( None, OTHER_UID )
                                 else { "jobs" : [], "total" : 0 } ):
            # B's DEFAULT view is empty and always was — that part is the permission
            # model working as designed, and is not what misled anyone.
            body = asyncio.run( get_job_history(
                current_user=REGULAR, status=None, job_type=None, limit=20,
                offset=0, days=None, exclude_ids=None, user_filter=None ) )
            assert body[ "total" ] == 0
            assert body[ "filtered_by" ] == REGULAR[ "uid" ]

            # B trying to WIDEN is now refused instead of being handed the narrow view
            # back with no indication the flag did nothing.
            with pytest.raises( HTTPException ) as exc:
                asyncio.run( get_job_history(
                    current_user=REGULAR, status=None, job_type=None, limit=20,
                    offset=0, days=None, exclude_ids=None, user_filter="*" ) )
            assert exc.value.status_code == 403

            # And an admin asking the same question gets the row that was there all along.
            admin_body = asyncio.run( get_job_history(
                current_user=ADMIN, status=None, job_type=None, limit=20,
                offset=0, days=None, exclude_ids=None, user_filter="*" ) )
            assert admin_body[ "total" ] == 1
            assert admin_body[ "jobs" ][ 0 ][ "id_hash" ] == "ts-1e2a1cb8"


if __name__ == "__main__":
    unittest.main()
