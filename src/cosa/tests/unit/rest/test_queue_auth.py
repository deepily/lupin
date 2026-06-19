"""
Unit tests for cosa.rest.queue_auth.authorize_queue_filter.

Exercises the full role-based authorization matrix for queue filtering. The sole
external seam — is_admin() from auth_middleware — is mocked so each role decision is
driven deterministically ( no real auth/DB/JWT ). Covers every branch:

    | Role  | filter_user_id | Result          |
    |-------|----------------|-----------------|
    | any   | None           | own uid         |
    | user  | "*"            | 403             |
    | admin | "*"            | "*"             |
    | user  | "!self"        | 403             |
    | admin | "!self"        | "!<uid>"        |
    | user  | other_id       | 403             |
    | admin | other_id       | other_id        |
    | any   | own_id         | own_id          |
"""

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from cosa.rest.queue_auth import authorize_queue_filter


class TestAuthorizeQueueFilter( unittest.TestCase ):
    """
    Tests for authorize_queue_filter().

    Requires:
        - is_admin() mocked to control the admin/non-admin decision

    Ensures:
        - Every authorization-matrix row is covered
        - 403 HTTPException raised for unauthorized regular-user operations
    """

    def setUp( self ):
        """
        Ensures:
            - A reusable authenticated-user dict is available
        """
        self.user = { "uid": "user_123", "roles": [ "user" ] }

    def _assert_forbidden( self, current_user, filter_user_id ):
        """
        Requires:
            - is_admin already patched False for this call

        Ensures:
            - authorize_queue_filter raises HTTPException(403)
        """
        with self.assertRaises( HTTPException ) as ctx:
            authorize_queue_filter( current_user, filter_user_id )
        self.assertEqual( ctx.exception.status_code, 403 )

    # ---- filter_user_id is None ---------------------------------------------

    @patch( 'cosa.rest.queue_auth.is_admin', return_value=False )
    def test_none_filter_returns_own_uid_for_user( self, _mock_is_admin ):
        """
        Ensures:
            - No filter -> requesting user's own uid ( regular user )
        """
        self.assertEqual( authorize_queue_filter( self.user, None ), "user_123" )

    @patch( 'cosa.rest.queue_auth.is_admin', return_value=True )
    def test_none_filter_returns_own_uid_for_admin( self, _mock_is_admin ):
        """
        Ensures:
            - No filter -> requesting user's own uid ( admin too )
        """
        admin = { "uid": "admin_1", "roles": [ "admin" ] }
        self.assertEqual( authorize_queue_filter( admin, None ), "admin_1" )

    # ---- wildcard "*" --------------------------------------------------------

    @patch( 'cosa.rest.queue_auth.is_admin', return_value=False )
    def test_wildcard_forbidden_for_user( self, _mock_is_admin ):
        """
        Ensures:
            - Regular user requesting "*" is forbidden ( 403 )
        """
        self._assert_forbidden( self.user, "*" )

    @patch( 'cosa.rest.queue_auth.is_admin', return_value=True )
    def test_wildcard_allowed_for_admin( self, _mock_is_admin ):
        """
        Ensures:
            - Admin requesting "*" receives the wildcard
        """
        admin = { "uid": "admin_1", "roles": [ "admin" ] }
        self.assertEqual( authorize_queue_filter( admin, "*" ), "*" )

    # ---- "!self" -------------------------------------------------------------

    @patch( 'cosa.rest.queue_auth.is_admin', return_value=False )
    def test_not_self_forbidden_for_user( self, _mock_is_admin ):
        """
        Ensures:
            - Regular user requesting "!self" is forbidden ( 403 )
        """
        self._assert_forbidden( self.user, "!self" )

    @patch( 'cosa.rest.queue_auth.is_admin', return_value=True )
    def test_not_self_returns_exclusion_sentinel_for_admin( self, _mock_is_admin ):
        """
        Ensures:
            - Admin requesting "!self" receives the "!<uid>" exclusion sentinel
        """
        admin = { "uid": "admin_1", "roles": [ "admin" ] }
        self.assertEqual( authorize_queue_filter( admin, "!self" ), "!admin_1" )

    # ---- specific other user_id ---------------------------------------------

    @patch( 'cosa.rest.queue_auth.is_admin', return_value=False )
    def test_other_user_forbidden_for_user( self, _mock_is_admin ):
        """
        Ensures:
            - Regular user requesting another user's id is forbidden ( 403 )
        """
        self._assert_forbidden( self.user, "someone_else_9999" )

    @patch( 'cosa.rest.queue_auth.is_admin', return_value=True )
    def test_other_user_allowed_for_admin( self, _mock_is_admin ):
        """
        Ensures:
            - Admin requesting another user's id receives that id
        """
        admin = { "uid": "admin_1", "roles": [ "admin" ] }
        self.assertEqual( authorize_queue_filter( admin, "someone_else_9999" ), "someone_else_9999" )

    # ---- own id ( filter equals self ) --------------------------------------

    @patch( 'cosa.rest.queue_auth.is_admin', return_value=False )
    def test_own_id_returned_for_user( self, _mock_is_admin ):
        """
        Ensures:
            - Regular user requesting their OWN id passes the equality guard and
              receives it ( covers the `filter_user_id != requesting_user_id` False arm )
        """
        self.assertEqual( authorize_queue_filter( self.user, "user_123" ), "user_123" )


if __name__ == "__main__":
    unittest.main()
