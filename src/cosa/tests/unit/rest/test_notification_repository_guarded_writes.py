"""
The two writes of NotificationRepository that guard a human answer.

`mark_answer_delivered` stamps the handback mark and nothing else.
`mark_expired` with an expected state lets the committed row decide: no match, no write.
The database is replaced by a mock session, so no case touches Postgres.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from cosa.rest.db.repositories.notification_repository import NotificationRepository

_RID = uuid.UUID( "22222222-2222-2222-2222-222222222222" )


@pytest.fixture
def repo():
    return NotificationRepository( MagicMock( name="session" ) )


def _note( **kw ):
    base = dict( state="pending", response_default=None, response_value=None, answer_delivered_at=None )
    base.update( kw )
    return SimpleNamespace( **base )


def _query_matching( session, matched ):
    """Make the guarded write report `matched` rows; return the query mock."""
    q = MagicMock( name="query" )
    q.filter.return_value = q
    q.update.return_value = matched
    session.query.return_value = q
    return q


def test_marking_an_answer_delivered_stamps_only_the_handback_mark( repo ):
    note = _note( state="responded" )
    with patch.object( repo, "get_by_id", return_value=note ):
        before = datetime.now( timezone.utc )
        out    = repo.mark_answer_delivered( _RID )
    assert out is note
    assert note.answer_delivered_at.tzinfo is not None and note.answer_delivered_at >= before
    assert note.state == "responded" and note.response_value is None
    repo.session.flush.assert_called_once()


def test_marking_a_missing_notification_delivered_returns_none_and_writes_nothing( repo ):
    with patch.object( repo, "get_by_id", return_value=None ):
        assert repo.mark_answer_delivered( _RID ) is None
    repo.session.flush.assert_not_called()


def test_a_guarded_expiry_writes_when_the_committed_row_is_still_in_the_expected_state( repo ):
    q    = _query_matching( repo.session, 1 )
    note = _note( state="expired", response_default="Approve" )
    with patch.object( repo, "get_by_id", return_value=note ):
        out = repo.mark_expired( _RID, expected_state="pending" )
    assert out is note
    assert q.update.call_args.args[ 0 ] == { "state": "expired" }
    assert q.update.call_args.kwargs == { "synchronize_session": "fetch" }
    assert note.response_value == { "value": "Approve", "source": "timeout_default" }
    repo.session.flush.assert_called_once()


def test_a_guarded_expiry_without_the_default_writes_no_answer( repo ):
    _query_matching( repo.session, 1 )
    note = _note( response_default="Approve" )
    with patch.object( repo, "get_by_id", return_value=note ):
        assert repo.mark_expired( _RID, apply_default=False, expected_state="pending" ) is note
    assert note.response_value is None


def test_a_guarded_expiry_writes_nothing_when_the_row_already_moved_on( repo ):
    _query_matching( repo.session, 0 )
    with patch.object( repo, "get_by_id", side_effect=AssertionError( "must not re-read" ) ):
        assert repo.mark_expired( _RID, expected_state="pending" ) is None
    repo.session.flush.assert_not_called()


def test_a_guarded_expiry_returns_none_when_the_row_vanishes_after_the_write( repo ):
    _query_matching( repo.session, 1 )
    with patch.object( repo, "get_by_id", return_value=None ):
        assert repo.mark_expired( _RID, expected_state="pending" ) is None
    repo.session.flush.assert_not_called()
