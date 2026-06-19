"""
Unit tests for cosa.rest.auth_audit.

All persistence seams are mocked — get_db ( session context manager ) and
AuthAuditLogRepository — plus uuid. NO real database. Covers the branch-heavy
audit-log read/write helpers:

    - log_auth_event          ( uuid present/absent/invalid; details str/dict/None; failure )
    - get_user_audit_log      ( success row-mapping variants; invalid uuid; failure )
    - get_failed_logins       ( email filter on/off; row-mapping; failure )
    - get_suspicious_activity ( grouping + threshold + sort; failure )
"""

import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from cosa.rest.auth_audit import (
    log_auth_event,
    get_user_audit_log,
    get_failed_logins,
    get_suspicious_activity,
)


def _log( event_type="login_failure", user_id="u-1", email="a@b.com",
          ip="1.2.3.4", details=None, success=False, event_time=None ):
    """
    Requires:
        - field overrides for a fake audit-log ORM row

    Ensures:
        - Returns a MagicMock with the audit-log row attributes set
    """
    row = MagicMock()
    row.event_type = event_type
    row.user_id    = user_id
    row.email      = email
    row.ip_address = ip
    row.details    = details if details is not None else { "message": "msg" }
    row.success    = success
    row.event_time = event_time
    return row


class TestLogAuthEvent( unittest.TestCase ):
    """
    Tests for log_auth_event().

    Ensures:
        - user_id present/absent/invalid arms
        - details str / dict / None normalization
        - exceptions are swallowed ( never raises )
    """

    def test_valid_user_id_and_str_details( self ):
        """
        Ensures:
            - Valid user_id is UUID-converted; string details wrapped as {"message": ...}
        """
        with patch( 'cosa.rest.auth_audit.get_db' ) as mock_db, \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.auth_audit.uuid' ) as mock_uuid:
            mock_uuid.UUID.return_value = "UUID_OBJ"
            repo = mock_repo_cls.return_value
            log_auth_event( "login_success", user_id="uid", email="a@b.com", details="hello", success=True )
            _, kwargs = repo.log_event.call_args
            self.assertEqual( kwargs[ "user_id" ], "UUID_OBJ" )
            self.assertEqual( kwargs[ "details" ], { "message": "hello" } )
            self.assertEqual( kwargs[ "email" ], "a@b.com" )

    def test_no_user_id_and_none_details_defaults( self ):
        """
        Ensures:
            - Absent user_id -> None; None details -> {}; email/ip default to "unknown"
        """
        with patch( 'cosa.rest.auth_audit.get_db' ), \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.auth_audit.uuid' ):
            repo = mock_repo_cls.return_value
            log_auth_event( "login_failure", user_id=None, details=None )
            _, kwargs = repo.log_event.call_args
            self.assertIsNone( kwargs[ "user_id" ] )
            self.assertEqual( kwargs[ "details" ], {} )
            self.assertEqual( kwargs[ "email" ], "unknown" )
            self.assertEqual( kwargs[ "ip_address" ], "unknown" )

    def test_dict_details_passed_through( self ):
        """
        Ensures:
            - Non-str truthy details ( dict ) pass through unwrapped
        """
        with patch( 'cosa.rest.auth_audit.get_db' ), \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.auth_audit.uuid' ):
            repo = mock_repo_cls.return_value
            log_auth_event( "register", user_id=None, details={ "k": "v" } )
            _, kwargs = repo.log_event.call_args
            self.assertEqual( kwargs[ "details" ], { "k": "v" } )

    def test_invalid_user_id_logs_anyway( self ):
        """
        Ensures:
            - An un-parseable user_id prints a warning and logs with user_id None
        """
        with patch( 'cosa.rest.auth_audit.get_db' ), \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.auth_audit.uuid' ) as mock_uuid, \
             patch( 'builtins.print' ):
            mock_uuid.UUID.side_effect = ValueError( "bad uuid" )
            repo = mock_repo_cls.return_value
            log_auth_event( "login_success", user_id="not-a-uuid" )
            _, kwargs = repo.log_event.call_args
            self.assertIsNone( kwargs[ "user_id" ] )

    def test_exception_swallowed( self ):
        """
        Ensures:
            - A repository failure is caught and printed, not raised
        """
        with patch( 'cosa.rest.auth_audit.get_db' ) as mock_db, \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.auth_audit.uuid' ), \
             patch( 'builtins.print' ):
            mock_repo_cls.return_value.log_event.side_effect = Exception( "db down" )
            # Should not raise
            log_auth_event( "login_success", user_id=None )


class TestGetUserAuditLog( unittest.TestCase ):
    """
    Tests for get_user_audit_log().

    Ensures:
        - Row-mapping covers user_id present/None, dict/non-dict details, event_time present/None
        - Invalid uuid and generic exceptions return []
    """

    def test_success_maps_rows_both_variants( self ):
        """
        Ensures:
            - Two rows exercise both arms of the user_id / details / event_time ternaries
        """
        row_full = _log( user_id="u-1", details={ "message": "hi" }, event_time=datetime( 2025, 9, 29, 12, 0, 0 ) )
        row_bare = _log( user_id=None, details="raw-string", event_time=None )
        with patch( 'cosa.rest.auth_audit.get_db' ), \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.auth_audit.uuid' ) as mock_uuid:
            mock_uuid.UUID.return_value = "UUID_OBJ"
            mock_repo_cls.return_value.get_by_user.return_value = [ row_full, row_bare ]
            result = get_user_audit_log( "uid", limit=10 )
            self.assertEqual( len( result ), 2 )
            self.assertEqual( result[0][ "user_id" ], "u-1" )
            self.assertEqual( result[0][ "details" ], "hi" )           # dict -> message
            self.assertEqual( result[0][ "event_time" ], "2025-09-29T12:00:00" )
            self.assertIsNone( result[1][ "user_id" ] )               # None user_id
            self.assertEqual( result[1][ "details" ], "raw-string" )  # non-dict -> str()
            self.assertIsNone( result[1][ "event_time" ] )            # None event_time

    def test_invalid_uuid_returns_empty( self ):
        """
        Ensures:
            - A ValueError from uuid.UUID returns [] ( via the ValueError handler )
        """
        with patch( 'cosa.rest.auth_audit.uuid' ) as mock_uuid, \
             patch( 'builtins.print' ):
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            self.assertEqual( get_user_audit_log( "bad" ), [] )

    def test_generic_exception_returns_empty( self ):
        """
        Ensures:
            - A non-ValueError failure returns []
        """
        with patch( 'cosa.rest.auth_audit.get_db' ) as mock_db, \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls, \
             patch( 'cosa.rest.auth_audit.uuid' ), \
             patch( 'builtins.print' ):
            mock_repo_cls.return_value.get_by_user.side_effect = Exception( "db error" )
            self.assertEqual( get_user_audit_log( "uid" ), [] )


class TestGetFailedLogins( unittest.TestCase ):
    """
    Tests for get_failed_logins().

    Ensures:
        - Email filter on ( case-insensitive, skips None emails ) and off
        - Generic exception returns []
    """

    def test_email_filter_applied( self ):
        """
        Ensures:
            - With an email filter, only case-insensitive matches ( with non-None email ) survive
        """
        match     = _log( email="Target@Example.com" )
        other     = _log( email="someone@else.com" )
        no_email  = _log( email=None )
        with patch( 'cosa.rest.auth_audit.get_db' ), \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls:
            mock_repo_cls.return_value.get_failed_events.return_value = [ match, other, no_email ]
            result = get_failed_logins( email="target@example.com", limit=10 )
            self.assertEqual( len( result ), 1 )
            self.assertEqual( result[0][ "email" ], "Target@Example.com" )

    def test_no_email_filter_returns_all( self ):
        """
        Ensures:
            - Without an email filter, all failed events map through
        """
        with patch( 'cosa.rest.auth_audit.get_db' ), \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls:
            mock_repo_cls.return_value.get_failed_events.return_value = [ _log(), _log() ]
            result = get_failed_logins( limit=10 )
            self.assertEqual( len( result ), 2 )

    def test_exception_returns_empty( self ):
        """
        Ensures:
            - A repository failure returns []
        """
        with patch( 'cosa.rest.auth_audit.get_db' ), \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls, \
             patch( 'builtins.print' ):
            mock_repo_cls.return_value.get_failed_events.side_effect = Exception( "db error" )
            self.assertEqual( get_failed_logins(), [] )


class TestGetSuspiciousActivity( unittest.TestCase ):
    """
    Tests for get_suspicious_activity().

    Ensures:
        - Groups failed events by email, applies threshold, sorts descending
        - Skips None emails; failure returns []
    """

    def test_threshold_grouping_and_sort( self ):
        """
        Ensures:
            - Emails at/above threshold are returned, sorted by count desc; None emails skipped
        """
        # heavy@x.com: 3, light@x.com: 1, None-email: 1
        logs = (
            [ _log( email="heavy@x.com" ) for _ in range( 3 ) ]
            + [ _log( email="light@x.com" ) ]
            + [ _log( email=None ) ]
        )
        with patch( 'cosa.rest.auth_audit.get_db' ), \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls:
            mock_repo_cls.return_value.get_failed_events.return_value = logs
            result = get_suspicious_activity( hours=24, threshold=2 )
            self.assertEqual( result, [ ( "heavy@x.com", 3 ) ] )

    def test_exception_returns_empty( self ):
        """
        Ensures:
            - A repository failure returns []
        """
        with patch( 'cosa.rest.auth_audit.get_db' ), \
             patch( 'cosa.rest.auth_audit.AuthAuditLogRepository' ) as mock_repo_cls, \
             patch( 'builtins.print' ):
            mock_repo_cls.return_value.get_failed_events.side_effect = Exception( "db error" )
            self.assertEqual( get_suspicious_activity(), [] )


if __name__ == "__main__":
    unittest.main()
