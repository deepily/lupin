#!/usr/bin/env python3
"""
Unit — FcmTokenRepository (durable token registry, S6 §3.1 / F-S6-S2-1a).

Mocked-session unit tier (existing repository-test convention). The AC-S6.1
re-instantiate-from-store REHYDRATION proof runs at the integration tier
against the real database (src/tests/integration/test_fcm_token_registration.py)
— a mocked session cannot prove durability.

Venue: :7999 (pure unit — MagicMock session).
"""

import os
import sys
from unittest.mock import MagicMock

import pytest

# Bootstrap
_src_path = os.path.join( os.environ.get( "LUPIN_ROOT", os.getcwd() ), "src" )
if _src_path not in sys.path:
    sys.path.insert( 0, _src_path )

from cosa.rest.db.repositories.fcm_token_repository import FcmTokenRepository
from cosa.rest.postgres_models import FcmToken


@pytest.fixture
def mock_session():
    return MagicMock()


@pytest.fixture
def repo( mock_session ):
    return FcmTokenRepository( mock_session )


class TestUpsertToken:

    def test_new_token_adds_row( self, repo, mock_session ):
        mock_session.query.return_value.filter.return_value.first.return_value = None

        row = repo.upsert_token( token="tok-1", user_id="u-1", user_email="rick@example.com" )

        mock_session.add.assert_called_once()
        mock_session.flush.assert_called_once()
        assert isinstance( row, FcmToken )
        assert row.token      == "tok-1"
        assert row.user_id    == "u-1"
        assert row.user_email == "rick@example.com"
        assert row.platform   == "android"

    def test_known_token_updates_in_place( self, repo, mock_session ):
        existing = FcmToken( token="tok-1", user_id="old-user", user_email="old@example.com", platform="android" )
        mock_session.query.return_value.filter.return_value.first.return_value = existing

        row = repo.upsert_token( token="tok-1", user_id="new-user", user_email="new@example.com", platform="android" )

        assert row is existing
        assert row.user_id            == "new-user"
        assert row.user_email         == "new@example.com"
        assert row.last_registered_at is not None
        mock_session.add.assert_not_called()    # upsert, never a duplicate row
        mock_session.flush.assert_called_once()

    def test_explicit_platform_respected( self, repo, mock_session ):
        mock_session.query.return_value.filter.return_value.first.return_value = None
        row = repo.upsert_token( token="tok-1", user_id="u-1", user_email="r@e.com", platform="android-tv" )
        assert row.platform == "android-tv"


class TestDeleteToken:

    def test_known_token_deleted_returns_true( self, repo, mock_session ):
        mock_session.query.return_value.filter.return_value.delete.return_value = 1
        assert repo.delete_token( "tok-1" ) is True
        mock_session.flush.assert_called_once()

    def test_unknown_token_returns_false( self, repo, mock_session ):
        mock_session.query.return_value.filter.return_value.delete.return_value = 0
        assert repo.delete_token( "never-seen" ) is False


class TestGetTokensForUser:

    def test_returns_token_strings( self, repo, mock_session ):
        row_1 = MagicMock(); row_1.token = "tok-1"
        row_2 = MagicMock(); row_2.token = "tok-2"
        mock_session.query.return_value.filter.return_value.all.return_value = [ row_1, row_2 ]
        assert repo.get_tokens_for_user( "u-1" ) == [ "tok-1", "tok-2" ]

    def test_unknown_user_returns_empty_list_not_none( self, repo, mock_session ):
        mock_session.query.return_value.filter.return_value.all.return_value = []
        assert repo.get_tokens_for_user( "ghost" ) == []


class TestGetByToken:

    def test_returns_row_or_none( self, repo, mock_session ):
        row = MagicMock()
        mock_session.query.return_value.filter.return_value.first.return_value = row
        assert repo.get_by_token( "tok-1" ) is row
        mock_session.query.return_value.filter.return_value.first.return_value = None
        assert repo.get_by_token( "tok-2" ) is None


if __name__ == "__main__":
    sys.exit( pytest.main( [ __file__, "-v" ] ) )
