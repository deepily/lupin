#!/usr/bin/env python3
"""
Integration test (real Postgres) for bug ee59d5ed Change 1 — the durable,
HISTORY-SAFE reaped-sender roster eviction.

This is the LOAD-BEARING proof the unit tests (mocked session) cannot give: that
against real SQL, a sender with a persisted `session_reaped` marker is
    (AC-2) ABSENT from the focus-bar roster (get_sender_last_activities_visible), and
    (AC-3) still PRESENT in notification history (get_sender_conversation), and
    (rider 1) the `session_reaped` marker ROW actually EXISTS in the DB
             (the row's existence IS the durability — Change 2's sweep and normal
             dismiss both rely on it).

DB-backed + self-cleaning: seeds a LIVE sender (one task row) and a REAPED sender
(one task row + one session_reaped marker) for the test user, asserts, then
deletes every probe row in a finally.

Venue: :8000 (mutates DB state; runs in-container where get_db reaches the DB).
Submit via POST /api/test-suite/submit — never run against :7999.
"""
import os
import uuid

import pytest

BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
_EMAIL   = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )

pytestmark = pytest.mark.skipif(
    not _EMAIL,
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL env var",
)

# Fixed probe ids + sender_ids (unique ee59d5ed suffixes so no collision with real data).
_LIVE_SENDER   = "claude.code@lupin.deepily.ai#ee5900aa"
_REAPED_SENDER = "claude.code@lupin.deepily.ai#ee5900bb"
_ID_LIVE_TASK   = "0000ee59-0000-0000-0000-000000000001"
_ID_REAPED_TASK = "0000ee59-0000-0000-0000-000000000002"
_ID_REAPED_MARK = "0000ee59-0000-0000-0000-000000000003"
_ALL_IDS = ( _ID_LIVE_TASK, _ID_REAPED_TASK, _ID_REAPED_MARK )


def test_reaped_sender_evicted_from_roster_but_history_preserved():
    from sqlalchemy import text, bindparam
    from cosa.rest.db.database import get_db
    from cosa.rest.db.repositories.notification_repository import NotificationRepository

    with get_db() as session:
        row = session.execute( text( "SELECT id FROM users WHERE email = :e" ), { "e": _EMAIL } ).first()
        assert row is not None, f"test user {_EMAIL} not found"
        rid      = str( row[ 0 ] )
        rid_uuid = uuid.UUID( rid )
        repo     = NotificationRepository( session )

        def _insert( pid, sender, ntype ):
            session.execute( text(
                "INSERT INTO notifications "
                "(id, sender_id, recipient_id, message, type, priority, created_at, response_requested, state, is_hidden) VALUES "
                "(:pid,:snd,:rid,:msg,:typ,'low', now(), false, 'created', false)"
            ), { "pid": pid, "snd": sender, "rid": rid, "msg": f"ee59d5ed probe {ntype}", "typ": ntype } )

        try:
            _insert( _ID_LIVE_TASK,   _LIVE_SENDER,   "task" )            # live sender, normal work
            _insert( _ID_REAPED_TASK, _REAPED_SENDER, "task" )            # reaped sender's work row
            _insert( _ID_REAPED_MARK, _REAPED_SENDER, "session_reaped" )  # the durability marker
            session.commit()
            session.expire_all()

            # ── AC-2: the roster excludes the reaped sender, keeps the live one ──
            roster        = repo.get_sender_last_activities_visible( recipient_id=rid_uuid )
            roster_senders = { r[ "sender_id" ] for r in roster }
            assert _LIVE_SENDER   in roster_senders, "live sender must remain on the focus bar"
            assert _REAPED_SENDER not in roster_senders, \
                "reaped sender MUST be durably evicted from the roster (across refresh)"

            # ── AC-3: history for the reaped sender is PRESERVED (not hidden) ──
            # The real history getter returns the reaped sender's rows (ORM objects).
            convo = repo.get_sender_conversation( _REAPED_SENDER, rid_uuid )
            assert len( convo ) >= 1, "reaped sender's notification history must be preserved (audit)"
            # And its non-marker 'task' work row is still visible (is_hidden=false) —
            # a raw-SQL check (robust against ORM detachment) that the roster eviction
            # did NOT hide the reaped sender's actual history.
            visible_task = session.execute(
                text( "SELECT count(*) FROM notifications WHERE id = :pid AND is_hidden = false" ),
                { "pid": _ID_REAPED_TASK },
            ).scalar()
            assert visible_task == 1, "reaped sender's work notification must remain visible in history"

            # ── rider 1: the session_reaped marker ROW exists (the durability) ──
            session.expire_all()
            marker = session.execute(
                text( "SELECT type, is_hidden FROM notifications WHERE id = :pid" ),
                { "pid": _ID_REAPED_MARK },
            ).first()
            assert marker is not None and marker[ 0 ] == "session_reaped" and marker[ 1 ] is False, marker

            # ── invariant: NOTHING was is_hidden'd (roster eviction is NOT a soft-delete) ──
            hidden_count = session.execute(
                text( "SELECT count(*) FROM notifications WHERE id IN :ids AND is_hidden = true" )
                    .bindparams( bindparam( "ids", expanding=True ) ),
                { "ids": list( _ALL_IDS ) },
            ).scalar()
            assert hidden_count == 0, "reaped-roster eviction must not set is_hidden on any row"

        finally:
            session.execute(
                text( "DELETE FROM notifications WHERE id IN :ids" )
                    .bindparams( bindparam( "ids", expanding=True ) ),
                { "ids": list( _ALL_IDS ) },
            )
            session.commit()
