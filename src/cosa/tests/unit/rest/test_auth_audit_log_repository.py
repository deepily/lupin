"""
Unit tests for cosa.rest.db.repositories.auth_audit_log_repository.

SQLAlchemy session mocked ( fully chainable: filter/order_by/limit/offset ); inherited
BaseRepository.create mocked. No real DB. Covers log_event + the audit queries.
"""

import unittest
import uuid
from unittest.mock import patch, MagicMock

from cosa.rest.db.repositories.auth_audit_log_repository import AuthAuditLogRepository


def _repo():
    """
    Ensures:
        - Returns ( repo, session, query ) with a fully chainable query mock
    """
    session = MagicMock()
    q = session.query.return_value
    for attr in ( "filter", "order_by", "limit", "offset" ):
        getattr( q, attr ).return_value = q
    return AuthAuditLogRepository( session ), session, q


class TestAuthAuditLogRepository( unittest.TestCase ):
    """
    Tests for AuthAuditLogRepository.

    Ensures:
        - log_event lowercases email; queries/count/cleanup delegate correctly
    """

    def test_log_event_lowercases_email( self ):
        """
        Ensures:
            - log_event delegates to base.create with lowercased email + stamped time
        """
        repo, _, _ = _repo()
        with patch.object( repo, "create", return_value="created" ) as mock_create:
            uid = uuid.uuid4()
            result = repo.log_event( "login", uid, "USER@X.com", "1.2.3.4", { "k": "v" }, True )
            self.assertEqual( result, "created" )
            _, kwargs = mock_create.call_args
            self.assertEqual( kwargs[ "email" ], "user@x.com" )
            self.assertEqual( kwargs[ "event_type" ], "login" )
            self.assertTrue( kwargs[ "success" ] )
            self.assertEqual( kwargs[ "details" ], { "k": "v" } )

    def test_get_by_user( self ):
        """
        Ensures:
            - Returns paginated, ordered user events
        """
        repo, _, q = _repo()
        q.all.return_value = [ "e1" ]
        self.assertEqual( repo.get_by_user( uuid.uuid4(), limit=10, offset=5 ), [ "e1" ] )

    def test_get_by_event_type( self ):
        """
        Ensures:
            - Returns events filtered by type
        """
        repo, _, q = _repo()
        q.all.return_value = [ "e1", "e2" ]
        self.assertEqual( repo.get_by_event_type( "login" ), [ "e1", "e2" ] )

    def test_get_failed_events( self ):
        """
        Ensures:
            - Returns failed events within the window
        """
        repo, _, q = _repo()
        q.all.return_value = [ "f1" ]
        self.assertEqual( repo.get_failed_events( hours=24 ), [ "f1" ] )

    def test_get_by_ip( self ):
        """
        Ensures:
            - Returns events from an IP within the window
        """
        repo, _, q = _repo()
        q.all.return_value = [ "i1" ]
        self.assertEqual( repo.get_by_ip( "1.2.3.4" ), [ "i1" ] )

    def test_count_by_event_type( self ):
        """
        Ensures:
            - Returns the COUNT result
        """
        repo, _, q = _repo()
        q.count.return_value = 8
        self.assertEqual( repo.count_by_event_type( "login" ), 8 )

    def test_cleanup_old( self ):
        """
        Ensures:
            - Bulk-deletes old logs and returns the count
        """
        repo, session, q = _repo()
        q.delete.return_value = 12
        self.assertEqual( repo.cleanup_old( days_old=90 ), 12 )
        session.flush.assert_called_once()


if __name__ == "__main__":
    unittest.main()
