"""
Unit tests for cosa.rest.refresh_token_service.

Persistence + JWT seams are mocked: get_db, RefreshTokenRepository,
decode_and_validate_token, create_refresh_token, uuid, and ( for rotation )
get_user_by_id + the module's own validate/revoke/store helpers. The cheap
deterministic _hash_token ( sha256 ) runs for real. NO real DB / JWT / network.

Covers every branch of:
    _hash_token · store_refresh_token · validate_refresh_token · revoke_refresh_token
    · revoke_all_user_tokens · cleanup_expired_tokens · rotate_refresh_token
"""

import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from sqlalchemy.exc import IntegrityError

from cosa.rest.refresh_token_service import (
    _hash_token,
    store_refresh_token,
    validate_refresh_token,
    revoke_refresh_token,
    revoke_all_user_tokens,
    cleanup_expired_tokens,
    rotate_refresh_token,
)

MODULE = "cosa.rest.refresh_token_service"


class TestHashToken( unittest.TestCase ):
    """
    Tests for _hash_token().

    Ensures:
        - Deterministic SHA-256 hex digest
    """

    def test_deterministic_hex( self ):
        """
        Ensures:
            - Same input -> same 64-char hex; different input -> different hash
        """
        h = _hash_token( "abc" )
        self.assertEqual( h, _hash_token( "abc" ) )
        self.assertEqual( len( h ), 64 )
        self.assertNotEqual( h, _hash_token( "abd" ) )


class TestStoreRefreshToken( unittest.TestCase ):
    """
    Tests for store_refresh_token().

    Ensures:
        - Required-field guard, token decode failure, UUID parse failure,
          success, IntegrityError ( duplicate ), and generic DB error
    """

    def test_missing_required_fields( self ):
        """
        Ensures:
            - Absent user_id/token/jti -> (False, required message)
        """
        ok, msg = store_refresh_token( "", "tok", "jti" )
        self.assertFalse( ok )
        self.assertIn( "required", msg )

    def test_invalid_token_decode( self ):
        """
        Ensures:
            - A decode failure -> (False, "Invalid token...")
        """
        with patch( f"{MODULE}.decode_and_validate_token", side_effect=Exception( "bad sig" ) ):
            ok, msg = store_refresh_token( "uid", "tok", "jti" )
            self.assertFalse( ok )
            self.assertIn( "Invalid token", msg )

    def test_invalid_uuid_format( self ):
        """
        Ensures:
            - A non-UUID user_id/jti -> (False, "Invalid UUID format")
        """
        with patch( f"{MODULE}.decode_and_validate_token", return_value={ "exp": 1700000000 } ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad uuid" )
            ok, msg = store_refresh_token( "uid", "tok", "jti" )
            self.assertFalse( ok )
            self.assertIn( "Invalid UUID format", msg )

    def test_success( self ):
        """
        Ensures:
            - Valid inputs persist the hashed token -> (True, success)
        """
        with patch( f"{MODULE}.decode_and_validate_token", return_value={ "exp": 1700000000 } ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid, \
             patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_uuid.UUID.return_value = "UU"
            ok, msg = store_refresh_token( "uid", "tok", "jti", user_agent="UA", ip_address="1.2.3.4" )
            self.assertTrue( ok )
            self.assertIn( "stored successfully", msg )
            mock_repo_cls.return_value.create_token.assert_called_once()

    def test_duplicate_integrity_error( self ):
        """
        Ensures:
            - An IntegrityError -> (False, "Token already exists")
        """
        with patch( f"{MODULE}.decode_and_validate_token", return_value={ "exp": 1700000000 } ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid, \
             patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_uuid.UUID.return_value = "UU"
            mock_repo_cls.return_value.create_token.side_effect = IntegrityError( "stmt", "params", Exception( "dup" ) )
            ok, msg = store_refresh_token( "uid", "tok", "jti" )
            self.assertFalse( ok )
            self.assertIn( "already exists", msg )

    def test_generic_db_error( self ):
        """
        Ensures:
            - A generic DB exception -> (False, "Database error...")
        """
        with patch( f"{MODULE}.decode_and_validate_token", return_value={ "exp": 1700000000 } ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid, \
             patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_uuid.UUID.return_value = "UU"
            mock_repo_cls.return_value.create_token.side_effect = Exception( "db down" )
            ok, msg = store_refresh_token( "uid", "tok", "jti" )
            self.assertFalse( ok )
            self.assertIn( "Database error", msg )


class TestValidateRefreshToken( unittest.TestCase ):
    """
    Tests for validate_refresh_token().

    Ensures:
        - Empty token, decode failure, missing claims, bad JTI, not-found,
          revoked, hash-mismatch, success, and generic error
    """

    def test_empty_token( self ):
        """
        Ensures:
            - Empty token -> (False, "Token required", None)
        """
        ok, msg, data = validate_refresh_token( "" )
        self.assertFalse( ok )
        self.assertIsNone( data )

    def test_decode_failure( self ):
        """
        Ensures:
            - decode failure -> (False, "Token validation failed...", None)
        """
        with patch( f"{MODULE}.decode_and_validate_token", side_effect=Exception( "bad" ) ):
            ok, msg, data = validate_refresh_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Token validation failed", msg )

    def test_missing_claims( self ):
        """
        Ensures:
            - Missing jti/sub -> (False, "Invalid token claims", None)
        """
        with patch( f"{MODULE}.decode_and_validate_token", return_value={ "jti": None, "sub": None } ):
            ok, msg, data = validate_refresh_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Invalid token claims", msg )

    def test_invalid_jti_format( self ):
        """
        Ensures:
            - Un-parseable jti -> (False, "Invalid JTI format", None)
        """
        with patch( f"{MODULE}.decode_and_validate_token", return_value={ "jti": "x", "sub": "u" } ), \
             patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg, data = validate_refresh_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Invalid JTI format", msg )

    def _decode_ok( self ):
        """
        Ensures:
            - Returns a decode patch with valid claims + a uuid patch
        """
        return (
            patch( f"{MODULE}.decode_and_validate_token", return_value={ "jti": "x", "sub": "u" } ),
            patch( f"{MODULE}.uuid" ),
            patch( f"{MODULE}.get_db" ),
            patch( f"{MODULE}.RefreshTokenRepository" ),
        )

    def test_not_found( self ):
        """
        Ensures:
            - get_by_jti None -> (False, "Token not found...", None)
        """
        p_dec, p_uuid, p_db, p_repo = self._decode_ok()
        with p_dec, p_uuid, p_db, p_repo as mock_repo_cls:
            mock_repo_cls.return_value.get_by_jti.return_value = None
            ok, msg, data = validate_refresh_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "not found", msg )

    def test_revoked( self ):
        """
        Ensures:
            - A revoked token -> (False, "Token has been revoked", None)
        """
        p_dec, p_uuid, p_db, p_repo = self._decode_ok()
        with p_dec, p_uuid, p_db, p_repo as mock_repo_cls:
            mock_repo_cls.return_value.get_by_jti.return_value = MagicMock( revoked=True )
            ok, msg, data = validate_refresh_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "revoked", msg )

    def test_hash_mismatch( self ):
        """
        Ensures:
            - A token-hash mismatch -> (False, "Token hash mismatch", None)
        """
        p_dec, p_uuid, p_db, p_repo = self._decode_ok()
        with p_dec, p_uuid, p_db, p_repo as mock_repo_cls:
            mock_repo_cls.return_value.get_by_jti.return_value = MagicMock( revoked=False, token_hash="WRONG" )
            ok, msg, data = validate_refresh_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "hash mismatch", msg )

    def test_success_with_timestamps( self ):
        """
        Ensures:
            - Matching hash -> updates last_used + returns token_data ( iso timestamps )
        """
        p_dec, p_uuid, p_db, p_repo = self._decode_ok()
        with p_dec, p_uuid, p_db, p_repo as mock_repo_cls:
            row = MagicMock(
                revoked=False, token_hash=_hash_token( "tok" ),
                jti="JTI", user_id="UID",
                created_at=datetime( 2025, 9, 29, 12, 0, 0 ),
                expires_at=datetime( 2025, 10, 6, 12, 0, 0 ),
            )
            mock_repo_cls.return_value.get_by_jti.return_value = row
            ok, msg, data = validate_refresh_token( "tok" )
            self.assertTrue( ok )
            self.assertEqual( data[ "user_id" ], "UID" )
            self.assertEqual( data[ "created_at" ], "2025-09-29T12:00:00" )
            mock_repo_cls.return_value.update_last_used.assert_called_once()

    def test_success_with_null_timestamps( self ):
        """
        Ensures:
            - None created_at/expires_at map to None ( covers the iso-or-None arms )
        """
        p_dec, p_uuid, p_db, p_repo = self._decode_ok()
        with p_dec, p_uuid, p_db, p_repo as mock_repo_cls:
            row = MagicMock(
                revoked=False, token_hash=_hash_token( "tok" ),
                jti="JTI", user_id="UID", created_at=None, expires_at=None,
            )
            mock_repo_cls.return_value.get_by_jti.return_value = row
            ok, msg, data = validate_refresh_token( "tok" )
            self.assertTrue( ok )
            self.assertIsNone( data[ "created_at" ] )
            self.assertIsNone( data[ "expires_at" ] )

    def test_generic_error( self ):
        """
        Ensures:
            - A DB exception -> (False, "Validation error...", None)
        """
        p_dec, p_uuid, p_db, p_repo = self._decode_ok()
        with p_dec, p_uuid, p_db, p_repo as mock_repo_cls:
            mock_repo_cls.return_value.get_by_jti.side_effect = Exception( "db error" )
            ok, msg, data = validate_refresh_token( "tok" )
            self.assertFalse( ok )
            self.assertIn( "Validation error", msg )


class TestRevokeRefreshToken( unittest.TestCase ):
    """
    Tests for revoke_refresh_token().

    Ensures:
        - Missing jti, bad jti, not-found, success, and failure paths
    """

    def test_missing_jti( self ):
        """
        Ensures:
            - Empty jti -> (False, "JTI required")
        """
        ok, msg = revoke_refresh_token( "" )
        self.assertFalse( ok )

    def test_invalid_jti( self ):
        """
        Ensures:
            - Un-parseable jti -> (False, "Invalid JTI format")
        """
        with patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg = revoke_refresh_token( "x" )
            self.assertFalse( ok )
            self.assertIn( "Invalid JTI format", msg )

    def test_not_found( self ):
        """
        Ensures:
            - revoke returns falsy -> (False, "Token not found")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.revoke.return_value = None
            ok, msg = revoke_refresh_token( "jti" )
            self.assertFalse( ok )
            self.assertIn( "not found", msg )

    def test_success( self ):
        """
        Ensures:
            - revoke returns a token -> (True, "revoked successfully")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.revoke.return_value = MagicMock()
            ok, msg = revoke_refresh_token( "jti" )
            self.assertTrue( ok )

    def test_failure( self ):
        """
        Ensures:
            - A DB exception -> (False, "Revocation failed...")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.revoke.side_effect = Exception( "boom" )
            ok, msg = revoke_refresh_token( "jti" )
            self.assertFalse( ok )
            self.assertIn( "Revocation failed", msg )


class TestRevokeAllUserTokens( unittest.TestCase ):
    """
    Tests for revoke_all_user_tokens().

    Ensures:
        - Missing user_id, bad uuid, success-with-count, and failure paths
    """

    def test_missing_user_id( self ):
        """
        Ensures:
            - Empty user_id -> (False, "User ID required")
        """
        ok, msg = revoke_all_user_tokens( "" )
        self.assertFalse( ok )

    def test_invalid_uuid( self ):
        """
        Ensures:
            - Bad user_id -> (False, "Invalid user ID format")
        """
        with patch( f"{MODULE}.uuid" ) as mock_uuid:
            mock_uuid.UUID.side_effect = ValueError( "bad" )
            ok, msg = revoke_all_user_tokens( "x" )
            self.assertFalse( ok )
            self.assertIn( "Invalid user ID format", msg )

    def test_success_with_count( self ):
        """
        Ensures:
            - Returns (True, "Revoked N token(s)")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.revoke_all_for_user.return_value = 4
            ok, msg = revoke_all_user_tokens( "uid" )
            self.assertTrue( ok )
            self.assertIn( "4", msg )

    def test_failure( self ):
        """
        Ensures:
            - A DB exception -> (False, "Revocation failed...")
        """
        with patch( f"{MODULE}.uuid" ), patch( f"{MODULE}.get_db" ), \
             patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.revoke_all_for_user.side_effect = Exception( "boom" )
            ok, msg = revoke_all_user_tokens( "uid" )
            self.assertFalse( ok )


class TestCleanupExpiredTokens( unittest.TestCase ):
    """
    Tests for cleanup_expired_tokens().

    Ensures:
        - Success returns count; failure returns (False, msg, 0)
    """

    def test_success( self ):
        """
        Ensures:
            - Returns (True, msg, deleted_count)
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.cleanup_expired.return_value = 7
            ok, msg, count = cleanup_expired_tokens()
            self.assertTrue( ok )
            self.assertEqual( count, 7 )

    def test_failure( self ):
        """
        Ensures:
            - A DB exception -> (False, msg, 0)
        """
        with patch( f"{MODULE}.get_db" ), patch( f"{MODULE}.RefreshTokenRepository" ) as mock_repo_cls:
            mock_repo_cls.return_value.cleanup_expired.side_effect = Exception( "boom" )
            ok, msg, count = cleanup_expired_tokens()
            self.assertFalse( ok )
            self.assertEqual( count, 0 )


class TestRotateRefreshToken( unittest.TestCase ):
    """
    Tests for rotate_refresh_token().

    Ensures:
        - Validate-fail, revoke-fail, user-not-found, store-fail, success, exception
    """

    def test_validate_fails( self ):
        """
        Ensures:
            - Invalid old token -> (False, "Invalid token...", None)
        """
        with patch( f"{MODULE}.validate_refresh_token", return_value=( False, "expired", None ) ):
            ok, msg, tok = rotate_refresh_token( "old" )
            self.assertFalse( ok )
            self.assertIsNone( tok )

    def test_revoke_fails( self ):
        """
        Ensures:
            - Failure to revoke the old token -> (False, "Failed to revoke...", None)
        """
        with patch( f"{MODULE}.validate_refresh_token", return_value=( True, "ok", { "user_id": "u", "jti": "j" } ) ), \
             patch( f"{MODULE}.revoke_refresh_token", return_value=( False, "nope" ) ):
            ok, msg, tok = rotate_refresh_token( "old" )
            self.assertFalse( ok )
            self.assertIn( "Failed to revoke", msg )

    def test_user_not_found( self ):
        """
        Ensures:
            - Missing user -> (False, "User not found", None)
        """
        with patch( f"{MODULE}.validate_refresh_token", return_value=( True, "ok", { "user_id": "u", "jti": "j" } ) ), \
             patch( f"{MODULE}.revoke_refresh_token", return_value=( True, "ok" ) ), \
             patch( "cosa.rest.user_service.get_user_by_id", return_value=None ):
            ok, msg, tok = rotate_refresh_token( "old" )
            self.assertFalse( ok )
            self.assertIn( "User not found", msg )

    def test_store_fails( self ):
        """
        Ensures:
            - Failure to store the new token -> (False, "Failed to store...", None)
        """
        with patch( f"{MODULE}.validate_refresh_token", return_value=( True, "ok", { "user_id": "u", "jti": "j" } ) ), \
             patch( f"{MODULE}.revoke_refresh_token", return_value=( True, "ok" ) ), \
             patch( "cosa.rest.user_service.get_user_by_id", return_value={ "email": "a@b.com" } ), \
             patch( f"{MODULE}.create_refresh_token", return_value="newtok" ), \
             patch( f"{MODULE}.decode_and_validate_token", return_value={ "jti": "newjti" } ), \
             patch( f"{MODULE}.store_refresh_token", return_value=( False, "db full" ) ):
            ok, msg, tok = rotate_refresh_token( "old" )
            self.assertFalse( ok )
            self.assertIn( "Failed to store", msg )

    def test_success( self ):
        """
        Ensures:
            - Full rotation -> (True, "rotated successfully", new_token)
        """
        with patch( f"{MODULE}.validate_refresh_token", return_value=( True, "ok", { "user_id": "u", "jti": "j" } ) ), \
             patch( f"{MODULE}.revoke_refresh_token", return_value=( True, "ok" ) ), \
             patch( "cosa.rest.user_service.get_user_by_id", return_value={ "email": "a@b.com" } ), \
             patch( f"{MODULE}.create_refresh_token", return_value="newtok" ), \
             patch( f"{MODULE}.decode_and_validate_token", return_value={ "jti": "newjti" } ), \
             patch( f"{MODULE}.store_refresh_token", return_value=( True, "stored" ) ):
            ok, msg, tok = rotate_refresh_token( "old" )
            self.assertTrue( ok )
            self.assertEqual( tok, "newtok" )

    def test_exception( self ):
        """
        Ensures:
            - An unexpected error during new-token generation -> (False, "Token rotation failed...", None)
        """
        with patch( f"{MODULE}.validate_refresh_token", return_value=( True, "ok", { "user_id": "u", "jti": "j" } ) ), \
             patch( f"{MODULE}.revoke_refresh_token", return_value=( True, "ok" ) ), \
             patch( "cosa.rest.user_service.get_user_by_id", side_effect=Exception( "boom" ) ):
            ok, msg, tok = rotate_refresh_token( "old" )
            self.assertFalse( ok )
            self.assertIn( "Token rotation failed", msg )


if __name__ == "__main__":
    unittest.main()
