"""
Unit tests for cosa.rest.middleware.api_key_auth.

All seams mocked — NO real DB / network / bcrypt-against-real-hash:
    - get_db()            → fake context-manager yielding a mock session
    - ApiKeyRepository    → mock repo with get_active_keys()
    - bcrypt.checkpw      → patched True/False (we test the dispatch, not bcrypt itself)
    - validate_api_key    → patched when exercising the require_* dependencies in isolation
    - cosa.rest.auth.verify_token → patched for the JWT branch

Covers validate_api_key, require_api_key, require_api_key_or_jwt across every
auth-reject arc (missing / bad-format / not-found key → 401, JWT success / failure).
The quick_smoke_test() block is campaign-excluded ( exclude_also ), not tested here.
"""

import asyncio
import unittest
from datetime import datetime
from unittest.mock import patch, MagicMock

from fastapi import HTTPException

import cosa.rest.middleware.api_key_auth as mw


# A syntactically valid key per the module regex: ck_live_ + 64 chars
VALID_KEY = "ck_live_" + "A" * 64


def _run( coro ):
    """
    Ensures:
        - Drives an async coroutine to completion on a fresh event loop
    """
    return asyncio.run( coro )


def _fake_db( session ):
    """
    Requires:
        - session is the object the `with get_db() as session` block should bind

    Ensures:
        - Returns a MagicMock usable as a context manager yielding `session`
    """
    ctx = MagicMock()
    ctx.__enter__.return_value = session
    ctx.__exit__.return_value  = False
    return ctx


class TestValidateApiKey( unittest.TestCase ):
    """
    Tests for validate_api_key.

    Ensures:
        - Matching active key → str(user_id) + last_used_at stamped
        - No match / empty set → None
        - Any internal error → None (swallowed)
    """

    def test_valid_key_returns_user_id_and_stamps_last_used( self ):
        """
        Ensures:
            - Returns str(user_id) when bcrypt matches an active key
            - Stamps last_used_at with a datetime
        """
        session  = MagicMock()
        key_obj  = MagicMock( user_id="11111111-2222-3333-4444-555555555555",
                              key_hash="$2b$hashed" )
        repo     = MagicMock()
        repo.get_active_keys.return_value = [ key_obj ]

        with patch.object( mw, "get_db", return_value=_fake_db( session ) ), \
             patch.object( mw, "ApiKeyRepository", return_value=repo ), \
             patch.object( mw.bcrypt, "checkpw", return_value=True ):
            result = _run( mw.validate_api_key( VALID_KEY ) )

        self.assertEqual( result, "11111111-2222-3333-4444-555555555555" )
        self.assertIsInstance( key_obj.last_used_at, datetime )

    def test_no_matching_key_returns_none( self ):
        """
        Ensures:
            - Returns None when no active key matches (bcrypt False for all)
        """
        session = MagicMock()
        repo    = MagicMock()
        repo.get_active_keys.return_value = [ MagicMock( key_hash="$2b$x" ) ]

        with patch.object( mw, "get_db", return_value=_fake_db( session ) ), \
             patch.object( mw, "ApiKeyRepository", return_value=repo ), \
             patch.object( mw.bcrypt, "checkpw", return_value=False ):
            result = _run( mw.validate_api_key( VALID_KEY ) )

        self.assertIsNone( result )

    def test_empty_active_keys_returns_none( self ):
        """
        Ensures:
            - Returns None when there are zero active keys (loop body never runs)
        """
        session = MagicMock()
        repo    = MagicMock()
        repo.get_active_keys.return_value = []

        with patch.object( mw, "get_db", return_value=_fake_db( session ) ), \
             patch.object( mw, "ApiKeyRepository", return_value=repo ):
            result = _run( mw.validate_api_key( VALID_KEY ) )

        self.assertIsNone( result )

    def test_internal_error_swallowed_returns_none( self ):
        """
        Ensures:
            - Any exception inside the DB block is caught → returns None
        """
        with patch.object( mw, "get_db", side_effect=RuntimeError( "db down" ) ):
            result = _run( mw.validate_api_key( VALID_KEY ) )

        self.assertIsNone( result )


class TestRequireApiKey( unittest.TestCase ):
    """
    Tests for require_api_key (API-key-only dependency).

    Ensures:
        - Missing / bad-format / unknown key → 401
        - Valid key → resolved user_id
    """

    def test_missing_header_raises_401( self ):
        """
        Ensures:
            - None header → 401 with a missing-key detail
        """
        with self.assertRaises( HTTPException ) as ctx:
            _run( mw.require_api_key( None ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Missing API key", ctx.exception.detail )

    def test_bad_format_raises_401( self ):
        """
        Ensures:
            - Malformed key (fails regex) → 401 before any DB lookup
        """
        with self.assertRaises( HTTPException ) as ctx:
            _run( mw.require_api_key( "not-a-valid-key" ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Invalid API key format", ctx.exception.detail )

    def test_unknown_key_raises_401( self ):
        """
        Ensures:
            - Valid format but validate_api_key→None → 401 invalid/inactive
        """
        with patch.object( mw, "validate_api_key", return_value=None ) as v:
            # validate_api_key is async → patch must return an awaitable
            async def _none( _k ): return None
            v.side_effect = _none
            with self.assertRaises( HTTPException ) as ctx:
                _run( mw.require_api_key( VALID_KEY ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Invalid or inactive", ctx.exception.detail )

    def test_valid_key_returns_user_id( self ):
        """
        Ensures:
            - Valid format + validate→user_id → that user_id returned
        """
        async def _uid( _k ): return "user-abc"
        with patch.object( mw, "validate_api_key", side_effect=_uid ):
            result = _run( mw.require_api_key( VALID_KEY ) )
        self.assertEqual( result, "user-abc" )


class TestRequireApiKeyOrJwt( unittest.TestCase ):
    """
    Tests for require_api_key_or_jwt (dual API-key OR Bearer-JWT dependency).

    Ensures:
        - API-key branch: bad format / unknown → 401, valid → user_id
        - JWT branch: success → uid, HTTPException re-raised, other error → 401
        - Neither header → 401 missing-auth
    """

    def test_api_key_bad_format_raises_401( self ):
        """
        Ensures:
            - API key present but malformed → 401 invalid-format
        """
        with self.assertRaises( HTTPException ) as ctx:
            _run( mw.require_api_key_or_jwt( x_api_key="bad", authorization=None ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Invalid API key format", ctx.exception.detail )

    def test_api_key_valid_returns_user_id( self ):
        """
        Ensures:
            - Valid API key resolving to a user_id short-circuits → user_id
        """
        async def _uid( _k ): return "svc-1"
        with patch.object( mw, "validate_api_key", side_effect=_uid ):
            result = _run( mw.require_api_key_or_jwt( x_api_key=VALID_KEY, authorization=None ) )
        self.assertEqual( result, "svc-1" )

    def test_api_key_valid_format_but_unknown_raises_401( self ):
        """
        Ensures:
            - Valid format + validate→None → 401 invalid/inactive (no JWT fallthrough)
        """
        async def _none( _k ): return None
        with patch.object( mw, "validate_api_key", side_effect=_none ):
            with self.assertRaises( HTTPException ) as ctx:
                _run( mw.require_api_key_or_jwt( x_api_key=VALID_KEY, authorization=None ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Invalid or inactive API key", ctx.exception.detail )

    def test_jwt_success_returns_uid( self ):
        """
        Ensures:
            - No API key + valid Bearer JWT → uid from verify_token
        """
        async def _verify( _t ): return { "uid": "jwt-user" }
        with patch( "cosa.rest.auth.verify_token", side_effect=_verify ):
            result = _run( mw.require_api_key_or_jwt(
                x_api_key=None, authorization="Bearer sometoken" ) )
        self.assertEqual( result, "jwt-user" )

    def test_jwt_http_exception_is_reraised( self ):
        """
        Ensures:
            - verify_token raising HTTPException propagates unchanged (not wrapped)
        """
        async def _raise( _t ):
            raise HTTPException( status_code=403, detail="forbidden token" )
        with patch( "cosa.rest.auth.verify_token", side_effect=_raise ):
            with self.assertRaises( HTTPException ) as ctx:
                _run( mw.require_api_key_or_jwt(
                    x_api_key=None, authorization="Bearer t" ) )
        self.assertEqual( ctx.exception.status_code, 403 )
        self.assertIn( "forbidden token", ctx.exception.detail )

    def test_jwt_generic_error_wrapped_as_401( self ):
        """
        Ensures:
            - verify_token raising a non-HTTP error → wrapped as 401 Invalid JWT
        """
        async def _boom( _t ):
            raise ValueError( "decode failure" )
        with patch( "cosa.rest.auth.verify_token", side_effect=_boom ):
            with self.assertRaises( HTTPException ) as ctx:
                _run( mw.require_api_key_or_jwt(
                    x_api_key=None, authorization="Bearer t" ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Invalid JWT", ctx.exception.detail )

    def test_no_headers_raises_missing_auth_401( self ):
        """
        Ensures:
            - Neither header present → 401 missing-auth
        """
        with self.assertRaises( HTTPException ) as ctx:
            _run( mw.require_api_key_or_jwt( x_api_key=None, authorization=None ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Missing auth", ctx.exception.detail )

    def test_non_bearer_authorization_falls_through_to_missing_auth( self ):
        """
        Ensures:
            - authorization present but not 'Bearer ' → startswith False → 401 missing-auth
        """
        with self.assertRaises( HTTPException ) as ctx:
            _run( mw.require_api_key_or_jwt( x_api_key=None, authorization="Basic abc" ) )
        self.assertEqual( ctx.exception.status_code, 401 )
        self.assertIn( "Missing auth", ctx.exception.detail )


if __name__ == "__main__":
    unittest.main()
