"""
Unit tests for the PostgreSQL ORM models (cosa.rest.postgres_models).

The module is pure SQLAlchemy 2.0 declarative — importing it executes every
column / relationship / index statement. The only executable methods are the 13
__repr__ helpers; this suite instantiates each transient model and exercises its
__repr__ to reach genuine 100% line + function coverage.

No database, no session, no flush: models are constructed transiently. Models
whose __repr__ slices a string field (token / id_hash) are given real strings so
the slice is exercised. ZERO DB.
"""

import unittest
import uuid

from cosa.rest import postgres_models as pm


_UID = uuid.UUID( "11111111-1111-1111-1111-111111111111" )


class TestModelReprs( unittest.TestCase ):
    """Each model's __repr__ returns a non-empty string and embeds key fields."""

    def test_user_repr( self ):
        r = repr( pm.User( id=_UID, email="a@b.com", is_active=True ) )
        self.assertIn( "User(", r )
        self.assertIn( "a@b.com", r )

    def test_refresh_token_repr( self ):
        r = repr( pm.RefreshToken( jti=_UID, user_id=_UID, revoked=False ) )
        self.assertIn( "RefreshToken(", r )

    def test_api_key_repr( self ):
        r = repr( pm.ApiKey( id=_UID, user_id=_UID, is_active=True ) )
        self.assertIn( "ApiKey(", r )

    def test_email_verification_token_repr( self ):
        r = repr( pm.EmailVerificationToken( token="tok12345abc", user_id=_UID, used=False ) )
        self.assertIn( "EmailVerificationToken(", r )
        self.assertIn( "tok12345", r )   # first 8 chars sliced

    def test_password_reset_token_repr( self ):
        r = repr( pm.PasswordResetToken( token="rst98765xyz", user_id=_UID, used=True ) )
        self.assertIn( "PasswordResetToken(", r )
        self.assertIn( "rst98765", r )

    def test_failed_login_attempt_repr( self ):
        r = repr( pm.FailedLoginAttempt( id=1, email="a@b.com", ip_address="1.2.3.4" ) )
        self.assertIn( "FailedLoginAttempt(", r )

    def test_notification_repr( self ):
        r = repr( pm.Notification( id=_UID, sender_id="s", state="created" ) )
        self.assertIn( "Notification(", r )

    def test_auth_audit_log_repr( self ):
        r = repr( pm.AuthAuditLog( id=1, event_type="login", user_id=_UID, success=True ) )
        self.assertIn( "AuthAuditLog(", r )

    def test_proxy_decision_repr( self ):
        r = repr( pm.ProxyDecision( id=_UID, domain="swe", category="cat", action="shadow" ) )
        self.assertIn( "ProxyDecision(", r )

    def test_trust_state_repr( self ):
        r = repr( pm.TrustState( user_email="a@b.com", domain="swe", category="cat", trust_level=2 ) )
        self.assertIn( "TrustState(", r )

    def test_prediction_log_repr( self ):
        r = repr( pm.PredictionLog( id=_UID, response_type="yes_no", category="cat", accuracy_match=True ) )
        self.assertIn( "PredictionLog(", r )

    def test_job_history_repr( self ):
        r = repr( pm.JobHistory( id_hash="abc123::user-1-longhash", job_type="deep_research", status="running" ) )
        self.assertIn( "JobHistory(", r )

    def test_server_lifecycle_repr( self ):
        r = repr( pm.ServerLifecycle( key="singleton", last_available_at="2026-01-01T00:00:00Z" ) )
        self.assertIn( "ServerLifecycle(", r )


def isolated_unit_test():
    """
    Run the postgres_models unit tests in isolation.

    Ensures:
        - Returns (success, duration, message) for the smoke-runner harness
    """
    import time
    start_time = time.time()
    suite = unittest.TestLoader().loadTestsFromModule( __import__( __name__ ) )
    result = unittest.TextTestRunner( verbosity=2 ).run( suite )
    duration = time.time() - start_time
    success = result.wasSuccessful()
    message = f"{result.testsRun} run, {len( result.failures )} failed, {len( result.errors )} errors"
    return success, duration, message


if __name__ == "__main__":
    ok, secs, msg = isolated_unit_test()
    print( f"\n{'✅ PASS' if ok else '❌ FAIL'} postgres_models tests in {secs:.3f}s — {msg}" )
