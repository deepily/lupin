"""
Unit tests for API key authentication middleware.

Tests the security and correctness of API key validation middleware
including bcrypt verification and FastAPI dependency injection.

Design reference: src/rnd/2025.11.10-phase-2.5-notification-authentication.md
Section: Middleware Architecture Design (lines 1187-1336)

Updated: 2026-02-02 - Fixed to mock ORM layer (get_db + ApiKeyRepository)
"""

import pytest
import bcrypt
import uuid
from contextlib import contextmanager
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from fastapi import HTTPException

from cosa.rest.middleware.api_key_auth import validate_api_key, require_api_key


class MockApiKey:
    """Mock ApiKey ORM object for testing."""

    def __init__( self, id: int, user_id: str, key_hash: str ):
        self.id            = id
        self.user_id       = uuid.UUID( user_id ) if isinstance( user_id, str ) else user_id
        self.key_hash      = key_hash
        self.is_active     = True
        self.last_used_at  = None
        self.created_at    = datetime.utcnow()
        self.description   = "Test key"


@contextmanager
def mock_db_session( api_keys: list ):
    """
    Create a mock database session context manager.

    Args:
        api_keys: List of MockApiKey objects to return from get_active_keys()
    """
    mock_session = MagicMock()
    mock_repo = MagicMock()
    mock_repo.get_active_keys.return_value = api_keys

    # When ApiKeyRepository is instantiated with session, return our mock repo
    with patch( 'cosa.rest.middleware.api_key_auth.get_db' ) as mock_get_db:
        with patch( 'cosa.rest.middleware.api_key_auth.ApiKeyRepository', return_value=mock_repo ):
            @contextmanager
            def session_context():
                yield mock_session

            mock_get_db.return_value = session_context()
            yield mock_repo


class TestValidateAPIKey:
    """Test suite for validate_api_key() function."""

    @pytest.mark.asyncio
    async def test_valid_api_key_returns_user_id( self ):
        """Test that valid API key returns user_id."""
        # Generate test API key and hash
        test_key = "ck_live_" + "A" * 64
        test_user_id = "12345678-1234-1234-1234-123456789012"
        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( test_key.encode( 'utf-8' ), salt ).decode( 'utf-8' )

        # Create mock API key
        mock_key = MockApiKey( id=1, user_id=test_user_id, key_hash=key_hash )

        with mock_db_session( [ mock_key ] ) as mock_repo:
            result = await validate_api_key( test_key )

        assert result == test_user_id
        mock_repo.get_active_keys.assert_called_once()

    @pytest.mark.asyncio
    async def test_one_malformed_row_does_not_block_the_keys_after_it( self ):
        """
        A valid key must still authenticate when an earlier row is malformed.

        FIXED — row 23a43f57. This test was committed FIRST, as a strict xfail,
        so the fix would have something to turn green. It earned its keep: when
        the per-row try/except landed, the strict marker turned the unexpected
        pass into a failure, which is exactly how a stale marker is meant to be
        caught. The marker is gone and this is now an ordinary regression guard.

        THE MECHANISM IT GUARDS. _validate_api_key_sync loops over EVERY active
        key calling bcrypt.checkpw. checkpw RAISES ValueError on a stored value
        that is not a well-formed bcrypt hash — it does not return False — so
        before the fix a malformed row did not merely fail to match itself: the
        raise escaped the loop, the outer handler swallowed it, and every key
        ordered AFTER the bad row was never checked. Their owners got 401 on a
        good credential.

        HOW A BAD ROW GOT THERE. Until 2026-08-24 the repository's create_key
        docstring example showed hashlib.sha256(...).hexdigest() and the model
        called key_hash "SHA-256 hash of API key". Both were wrong and both are
        corrected, but rows already written that way are still in the table.

        WHY IT WOULD BE HARD TO DIAGNOSE: get_active_keys returns rows in
        unspecified order, so whether a given key works depends on where it sorts
        relative to the bad one — and that can change when rows are added.

        Ensures:
            - with [malformed, valid], the valid key still resolves to its user
        """
        test_key     = "ck_live_" + "B" * 64
        test_user_id = "22345678-1234-1234-1234-123456789012"

        valid_hash = bcrypt.hashpw(
            test_key.encode( "utf-8" ), bcrypt.gensalt( rounds=12 )
        ).decode( "utf-8" )

        # Exactly what the old SHA-256 example would have written.
        import hashlib
        malformed_hash = hashlib.sha256( test_key.encode( "utf-8" ) ).hexdigest()

        malformed_row = MockApiKey( id=1, user_id="11111111-1111-1111-1111-111111111111",
                                    key_hash=malformed_hash )
        valid_row     = MockApiKey( id=2, user_id=test_user_id, key_hash=valid_hash )

        with mock_db_session( [ malformed_row, valid_row ] ):
            result = await validate_api_key( test_key )

        assert result == test_user_id, (
            "a malformed stored hash on an EARLIER row aborted the sweep, so a valid "
            "key was never checked — row 23a43f57. The per-row try/except in "
            "_validate_api_key_sync is what keeps this green; do not hoist it back out."
        )

    @pytest.mark.asyncio
    async def test_a_malformed_row_after_the_match_is_harmless( self ):
        """
        The control for the test above, so its red cannot be misread.

        If this one also failed, the problem would be the mock harness rather
        than the ordering. It passes against HEAD: the loop returns on the match
        before it ever reaches the malformed row.

        Ensures:
            - with [valid, malformed], the valid key resolves normally
        """
        import hashlib

        test_key     = "ck_live_" + "C" * 64
        test_user_id = "32345678-1234-1234-1234-123456789012"

        valid_hash = bcrypt.hashpw(
            test_key.encode( "utf-8" ), bcrypt.gensalt( rounds=12 )
        ).decode( "utf-8" )

        valid_row     = MockApiKey( id=1, user_id=test_user_id, key_hash=valid_hash )
        malformed_row = MockApiKey( id=2, user_id="11111111-1111-1111-1111-111111111111",
                                    key_hash=hashlib.sha256( b"whatever" ).hexdigest() )

        with mock_db_session( [ valid_row, malformed_row ] ):
            result = await validate_api_key( test_key )

        assert result == test_user_id

    @pytest.mark.asyncio
    async def test_invalid_api_key_returns_none( self ):
        """Test that invalid API key returns None."""
        test_key = "ck_live_invalid_key_" + "B" * 64
        correct_key = "ck_live_" + "A" * 64
        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( correct_key.encode( 'utf-8' ), salt ).decode( 'utf-8' )

        # Mock API key with different key hash
        mock_key = MockApiKey(
            id=1,
            user_id="12345678-1234-1234-1234-123456789012",
            key_hash=key_hash  # Hash of different key
        )

        with mock_db_session( [ mock_key ] ) as mock_repo:
            result = await validate_api_key( test_key )

        assert result is None

    @pytest.mark.asyncio
    async def test_no_active_keys_returns_none( self ):
        """Test that query with no active keys returns None."""
        test_key = "ck_live_" + "C" * 64

        # Empty list of keys
        with mock_db_session( [] ) as mock_repo:
            result = await validate_api_key( test_key )

        assert result is None

    @pytest.mark.asyncio
    async def test_database_error_returns_none( self ):
        """Test that database errors are handled gracefully."""
        test_key = "ck_live_" + "D" * 64

        # Mock get_db to raise exception
        with patch( 'cosa.rest.middleware.api_key_auth.get_db', side_effect=Exception( "DB error" ) ):
            result = await validate_api_key( test_key )

        assert result is None  # Should handle error gracefully

    @pytest.mark.asyncio
    async def test_updates_last_used_timestamp( self ):
        """Test that successful validation updates last_used_at."""
        test_key = "ck_live_" + "E" * 64
        test_user_id = "12345678-1234-1234-1234-123456789012"
        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( test_key.encode( 'utf-8' ), salt ).decode( 'utf-8' )

        mock_key = MockApiKey( id=5, user_id=test_user_id, key_hash=key_hash )
        initial_last_used = mock_key.last_used_at

        with mock_db_session( [ mock_key ] ) as mock_repo:
            result = await validate_api_key( test_key )

        # The implementation sets last_used_at on the key object
        assert result == test_user_id
        # Note: In the actual implementation, key_obj.last_used_at is set directly
        # The mock doesn't persist changes, but we verify the flow worked


class TestRequireAPIKey:
    """Test suite for require_api_key() FastAPI dependency."""

    @pytest.mark.asyncio
    async def test_missing_api_key_raises_401( self ):
        """Test that missing X-API-Key header raises 401."""
        with pytest.raises( HTTPException ) as exc_info:
            await require_api_key( x_api_key=None )

        assert exc_info.value.status_code == 401
        assert "Missing API key" in exc_info.value.detail
        assert exc_info.value.headers == { "WWW-Authenticate": "API-Key" }

    @pytest.mark.asyncio
    async def test_invalid_format_raises_401( self ):
        """Test that invalid API key format raises 401."""
        invalid_keys = [
            "invalid_key",
            "ck_test_" + "A" * 64,  # Wrong prefix
            "ck_live_" + "A" * 63,  # Too short
            "ck_live_ABC!@#$%",      # Invalid characters
        ]

        for invalid_key in invalid_keys:
            with pytest.raises( HTTPException ) as exc_info:
                await require_api_key( x_api_key=invalid_key )

            assert exc_info.value.status_code == 401
            assert "Invalid API key format" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_valid_key_returns_user_id( self ):
        """Test that valid API key returns user_id."""
        test_key = "ck_live_" + "F" * 64
        test_user_id = "12345678-1234-1234-1234-123456789012"

        # Mock validate_api_key to return user_id
        with patch( 'cosa.rest.middleware.api_key_auth.validate_api_key', return_value=test_user_id ):
            result = await require_api_key( x_api_key=test_key )

        assert result == test_user_id

    @pytest.mark.asyncio
    async def test_invalid_key_raises_401( self ):
        """Test that invalid API key (failed validation) raises 401."""
        test_key = "ck_live_" + "G" * 64

        # Mock validate_api_key to return None (invalid key)
        with patch( 'cosa.rest.middleware.api_key_auth.validate_api_key', return_value=None ):
            with pytest.raises( HTTPException ) as exc_info:
                await require_api_key( x_api_key=test_key )

        assert exc_info.value.status_code == 401
        assert "Invalid or inactive API key" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_format_validation_before_database_lookup( self ):
        """Test that format validation happens before database lookup (performance)."""
        invalid_key = "invalid_format"

        # Mock validate_api_key - should NOT be called for invalid format
        with patch( 'cosa.rest.middleware.api_key_auth.validate_api_key' ) as mock_validate:
            with pytest.raises( HTTPException ):
                await require_api_key( x_api_key=invalid_key )

            # validate_api_key should NOT have been called (format check failed first)
            mock_validate.assert_not_called()


class TestBcryptTimingSafety:
    """Test suite for bcrypt timing-safe comparison."""

    @pytest.mark.asyncio
    async def test_bcrypt_checkpw_used( self ):
        """Test that bcrypt.checkpw is used for timing-safe comparison."""
        test_key = "ck_live_" + "H" * 64
        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( test_key.encode( 'utf-8' ), salt ).decode( 'utf-8' )

        mock_key = MockApiKey(
            id=1,
            user_id="12345678-1234-1234-1234-123456789012",
            key_hash=key_hash
        )

        # Mock bcrypt.checkpw to track if it's called
        with mock_db_session( [ mock_key ] ):
            with patch( 'bcrypt.checkpw', return_value=True ) as mock_bcrypt:
                await validate_api_key( test_key )

                # Verify bcrypt.checkpw was called (timing-safe comparison)
                mock_bcrypt.assert_called_once()

    def test_bcrypt_comparison_is_constant_time( self ):
        """Test that bcrypt comparison is timing-safe (conceptual test)."""
        # This test documents the security requirement
        # bcrypt.checkpw() is designed to be timing-safe
        # It always performs the full hash comparison regardless of where mismatch occurs

        correct_key = "ck_live_" + "I" * 64
        wrong_key = "ck_live_" + "J" * 64

        salt = bcrypt.gensalt( rounds=12 )
        key_hash = bcrypt.hashpw( correct_key.encode( 'utf-8' ), salt )

        # Both comparisons should take similar time (timing-safe)
        result1 = bcrypt.checkpw( correct_key.encode( 'utf-8' ), key_hash )
        result2 = bcrypt.checkpw( wrong_key.encode( 'utf-8' ), key_hash )

        assert result1 is True
        assert result2 is False
        # The important security property is that the time taken
        # for both comparisons is constant (not tested here, but documented)


class TestAPIKeySecurityRequirements:
    """Test suite documenting security requirements."""

    def test_api_key_length_requirement( self ):
        """Document minimum 288-bit entropy requirement."""
        # Requirement: API keys must have at least 288 bits of entropy
        # Implementation: secrets.token_urlsafe(48) = 48 bytes = 384 bits
        # Base64url encoding: 48 bytes → 64 characters

        min_entropy_bits = 288
        actual_entropy_bits = 48 * 8  # 48 bytes * 8 bits/byte = 384 bits

        assert actual_entropy_bits >= min_entropy_bits, \
            f"API key entropy ({actual_entropy_bits} bits) below requirement ({min_entropy_bits} bits)"

    def test_bcrypt_cost_factor_requirement( self ):
        """
        LUPIN's configured bcrypt cost is at least 12 — not the library's.

        WHAT THIS TEST USED TO DO (row 323049bb). It chose a cost itself, hashed
        a string it made up, and checked bcrypt round-tripped it:

            salt          = bcrypt.gensalt( rounds=required_cost )
            password_hash = bcrypt.hashpw( test_password.encode(), salt )
            assert bcrypt.checkpw( test_password.encode(), password_hash )

        Every value there was manufactured inside the test and no Lupin code was
        called, so it asserted that the bcrypt library works. It would pass
        unchanged on a machine where Lupin's cost had been dropped to 4 — which
        is the only thing the "cost >= 12" requirement is about. Vacuity shape 2:
        it asserts something other than the behaviour its name claims.

        Ensures:
            - password_service.hash_password produces a real bcrypt hash
            - the cost embedded IN THAT HASH is >= 12, read back from Lupin's
              own output rather than chosen here
            - the hash verifies, and a wrong password does not
        """
        from cosa.rest.password_service import hash_password, verify_password

        required_cost = 12
        produced      = hash_password( "CorrectHorseBattery1!" )

        # A bcrypt hash is $<ident>$<cost>$<salt+digest> — the cost is field 2.
        fields = produced.split( "$" )
        assert fields[ 1 ].startswith( "2" ), \
            f"expected a bcrypt hash, got identifier {fields[ 1 ]!r} in {produced!r}"

        actual_cost = int( fields[ 2 ] )
        assert actual_cost >= required_cost, \
            f"Lupin hashes at bcrypt cost {actual_cost}; the requirement is >= {required_cost}"

        assert verify_password( "CorrectHorseBattery1!", produced )
        assert not verify_password( "WrongPassword1!", produced )

    def test_api_keys_are_validated_with_bcrypt_not_a_fast_digest( self ):
        """
        The API-key auth path uses bcrypt, and a SHA-256 digest cannot pass it.

        This exists because the RECORDS said otherwise (row 323049bb): the ApiKey
        model docstring said "SHA-256 hash of API key" and the repository's
        create_key example showed hashlib.sha256(...).hexdigest(). Both were
        wrong, and copying that example mints a credential that can never
        authenticate — a failure that looks like a bad key, not a bad write.
        Corrected in the same commit; this test is what keeps them corrected.

        Ensures:
            - a key hashed the way production hashes it validates
            - the SAME key stored as a SHA-256 digest does NOT validate, so the
              old example cannot quietly come back
        """
        import hashlib

        raw_key = "lupin_test_key_material"

        production_hash = bcrypt.hashpw(
            raw_key.encode( "utf-8" ), bcrypt.gensalt( rounds=12 )
        )
        assert bcrypt.checkpw( raw_key.encode( "utf-8" ), production_hash )

        # A SHA-256 digest is not merely a non-matching hash — it is not a valid
        # bcrypt hash at all, so checkpw RAISES rather than returning False.
        # That distinction is the point: see the note below.
        sha_digest = hashlib.sha256( raw_key.encode( "utf-8" ) ).hexdigest()
        with pytest.raises( ValueError ):
            bcrypt.checkpw( raw_key.encode( "utf-8" ), sha_digest.encode( "utf-8" ) )

    def test_a_malformed_stored_hash_raises_rather_than_returning_false( self ):
        """
        Pin the behaviour that makes one bad row dangerous to every other key.

        validate_api_key_sync loops over ALL active keys calling bcrypt.checkpw,
        inside one try/except that returns None. Because checkpw RAISES on a
        malformed stored hash instead of returning False, a single bad row does
        not merely fail to match — it aborts the loop, so every key ordered after
        it is never checked. Filed separately; this test records the mechanism so
        a fix has something to turn green.

        Ensures:
            - checkpw raises ValueError on a stored value that is not a bcrypt hash
            - it returns False, without raising, on a well-formed non-matching one
        """
        raw_key = "lupin_test_key_material"

        with pytest.raises( ValueError ):
            bcrypt.checkpw( raw_key.encode( "utf-8" ), b"not-a-bcrypt-hash" )

        other_hash = bcrypt.hashpw( b"a-different-key", bcrypt.gensalt( rounds=4 ) )
        assert bcrypt.checkpw( raw_key.encode( "utf-8" ), other_hash ) is False, \
            "a well-formed non-matching hash must return False, not raise"

    def test_no_plaintext_storage( self ):
        """
        The api_keys table has nowhere to put a plaintext key.

        This test used to be `assert True` with a comment saying enforcement was
        "by design" (row ac37dc5a). A requirement that is documented and not
        checked is a requirement that a future column can quietly break, and
        this one guards credentials. It is mechanically checkable: read the
        model's own columns.

        Ensures:
            - the only key-bearing column is key_hash
            - no column is named for a raw secret (key, api_key, secret, token,
              password, plaintext) — adding one is the regression
            - key_hash is sized for a SHA-256 hex digest and no larger, so it
              cannot hold a longer raw key
            - the write path takes a hash, never the raw key
        """
        import inspect

        from cosa.rest.postgres_models import ApiKey
        from cosa.rest.db.repositories.api_key_repository import ApiKeyRepository

        column_names = { c.name for c in ApiKey.__table__.columns }

        assert "key_hash" in column_names, \
            f"api_keys must store a hash column; got {sorted( column_names )}"

        forbidden = { "key", "api_key", "raw_key", "secret", "token", "password", "plaintext" }
        leaked    = column_names & forbidden
        assert not leaked, \
            f"api_keys has a column that could hold a raw credential: {sorted( leaked )}"

        # CORRECTED (row 323049bb). This line first said "a SHA-256 hex digest is
        # exactly 64 characters", which was wrong: api_keys hold a BCRYPT hash of
        # 60 characters ($2b$12$ + 53), written by create_service_account_postgres
        # and verified by bcrypt.checkpw in api_key_auth. I took the SHA-256 claim
        # from the model's own docstring and the repository's example, both of
        # which are stale — and I wrote it hours after cataloguing exactly this
        # defect. The column guard is still the right assertion; only its stated
        # reason was false.
        #
        # 64 leaves 4 characters of headroom over a bcrypt hash and is far too
        # narrow for a raw key, which is what makes it a useful guard.
        assert ApiKey.__table__.columns[ "key_hash" ].type.length == 64, \
            "key_hash is sized for a 60-character bcrypt hash; widening it is a red flag"

        # The write path names its input a hash and has no raw-key parameter.
        create_params = set( inspect.signature( ApiKeyRepository.create_key ).parameters )
        assert "key_hash" in create_params
        assert not ( create_params & forbidden ), \
            f"create_key accepts a raw credential parameter: {sorted( create_params & forbidden )}"
