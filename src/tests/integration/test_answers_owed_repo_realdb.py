"""
D-V3 / D-V4 / B-V2-twin — real-Postgres proof of the owed-answer repo query
(late-answer handback §4.4). Store row `7bb0a7df` (P1).

Exercises NotificationRepository.get_answers_owed_for_persona + mark_answer_delivered
against a REAL Postgres schema built by `alembic upgrade head` on a self-cleaning
throwaway DB — so the three-term owed predicate, the created_at age cap, the
responded_at cursor, and persona-keying are proven on the live query planner, not
a SQLite/metadata stand-in or a mocked session.

What it proves:
  1. **Per-term exclusion (D-V3 / B-V2 twin).** Four rows, one fully owed and three
     each failing EXACTLY ONE term of the predicate
     (response_requested / responded_at IS NOT NULL / answer_delivered_at IS NULL).
     The owed row is returned; each one-term-broken row is EXCLUDED **by id** —
     "returns nothing" is never the proof; an empty result is equally consistent
     with an empty table or a broken filter.
  2. **Cursor + age cap are on the RIGHT columns (D-V4).** The age cap keys on
     `created_at`: a 25h-old-created row answered 2 minutes ago is EXCLUDED under
     max_age_hours=24 yet PRESENT uncapped. The `since` cursor keys on
     `responded_at`: a 20h-old-created ask answered recently still delivers, and a
     `since` just before its answer time includes it while a `since` just after
     excludes it. A query that cursored/aged on the wrong column would strand the
     old-created/recently-answered row — the exact D-V4 bug.
  3. **Persona-keyed (ruling 6).** A fully-owed row under a DIFFERENT persona is
     excluded — the query matches sender_persona ALONE.
  4. **Ack semantics (ruling 2).** mark_answer_delivered removes the row from the
     owed set (answer_delivered_at now set) while the row STILL EXISTS in the table.

Venue: :7999-eligible (AI-discretionary). Self-cleaning pid-scoped throwaway DB on
the dev Postgres server; no server monopoly, SKIPS when Postgres is unreachable.
This is the repo-query layer of D-V3/D-V4/B-V2; the HTTP endpoint round-trip and
the auth-lane negative control (D-V1) are separate — the latter needs the
listener's answer_catchup.py fetch seam (Clayton, in flight).

Authored by the Tester (Rachel 🕊️, 2026-08-01) against Clayton's
get_answers_owed_for_persona / mark_answer_delivered (unit-green).
"""
import os
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import OperationalError

from alembic import command

from cosa.rest.db import database as db_module
from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.postgres_models import User, Notification
from cosa.rest.db.repositories.notification_repository import NotificationRepository
from cosa.rest.db.repositories.user_repository import UserRepository


_THROWAWAY_DB = f"answers_owed_repo_{os.getpid()}"
_PERSONA       = "tester_persona"
_OTHER_PERSONA = "someone_else"


def _server_url():
    db_module.swap_database( "testing" )
    return db_module.engine.url


def _maintenance_engine( server_url ):
    return create_engine( server_url, isolation_level="AUTOCOMMIT" )


@pytest.fixture( scope="module" )
def owed_session():
    """
    Throwaway DB → `alembic upgrade head` → yield a live Session. Drops the DB on
    teardown. SKIPS the module when Postgres is unreachable.
    """
    server_url = _server_url()
    try:
        eng = _maintenance_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
            conn.execute( text( f'CREATE DATABASE "{_THROWAWAY_DB}"' ) )
        eng.dispose()
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable — skipping real-DB owed-answer repo test: {e}" )

    throwaway_url = server_url.set( database=_THROWAWAY_DB ).render_as_string( hide_password=False )
    command.upgrade( build_alembic_config( database_url=throwaway_url ), "head" )

    engine  = create_engine( throwaway_url )
    Session = sessionmaker( bind=engine )
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        eng = _maintenance_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text(
                "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ), { "db": _THROWAWAY_DB } )
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
        eng.dispose()


def _make_user( session ) -> uuid.UUID:
    uid = uuid.uuid4()
    session.add( User(
        id            = uid,
        email         = f"owed-{uid.hex[:8]}@test.local",
        password_hash = "x",
        email_verified = True,
        is_active      = True,
        is_protected   = False,
        roles          = { "roles": [ "user" ] },
        created_at     = datetime.now( timezone.utc ),
    ) )
    session.flush()
    return uid


def _add_notif( session, recipient_id, *, persona=_PERSONA, response_requested=True,
                responded_ago=None, delivered=False, created_ago_hours=1,
                message="owed probe" ) -> uuid.UUID:
    """Insert one ask row with precise created_at / responded_at / answer_delivered_at."""
    now = datetime.now( timezone.utc )
    nid = uuid.uuid4()
    session.add( Notification(
        id                  = nid,
        sender_id           = f"claude.code@lupin.deepily.ai#{persona}sess",
        recipient_id        = recipient_id,
        message             = message,
        type                = "task",
        priority            = "high",
        created_at          = now - timedelta( hours=created_ago_hours ),
        sender_persona      = persona,
        response_requested  = response_requested,
        responded_at        = None if responded_ago is None else now - responded_ago,
        answer_delivered_at = now if delivered else None,
        state               = "created",
    ) )
    session.flush()
    return nid


def test_answers_owed_repo_realdb( owed_session ):
    session = owed_session
    repo    = NotificationRepository( session )
    rid     = _make_user( session )

    # ── Per-term (D-V3 / B-V2): one owed + three each failing ONE term ──────────
    id_owed      = _add_notif( session, rid, responded_ago=timedelta( minutes=2 ) )
    id_not_req   = _add_notif( session, rid, responded_ago=timedelta( minutes=2 ), response_requested=False )
    id_forged    = _add_notif( session, rid, responded_ago=None )                     # responded_at NULL = machine default
    id_delivered = _add_notif( session, rid, responded_ago=timedelta( minutes=2 ), delivered=True )
    id_other     = _add_notif( session, rid, responded_ago=timedelta( minutes=2 ), persona=_OTHER_PERSONA )
    session.commit()

    owed_ids = { n.id for n in repo.get_answers_owed_for_persona( _PERSONA, max_age_hours=24 ) }
    assert id_owed      in owed_ids, "the fully-owed row must be returned"
    assert id_not_req   not in owed_ids, "response_requested=False must be EXCLUDED (term 1)"
    assert id_forged    not in owed_ids, "responded_at NULL forged default must be EXCLUDED (term 2 — §3 invariant)"
    assert id_delivered not in owed_ids, "answer_delivered_at non-NULL must be EXCLUDED (term 3)"
    assert id_other     not in owed_ids, "a different persona's owed row must be EXCLUDED (ruling 6)"

    # ── D-V4: age cap on created_at; a 25h-created row answered 2min ago is out ──
    id_25h = _add_notif( session, rid, responded_ago=timedelta( minutes=2 ), created_ago_hours=25, message="25h old" )
    session.commit()
    capped_ids   = { n.id for n in repo.get_answers_owed_for_persona( _PERSONA, max_age_hours=24 ) }
    uncapped_ids = { n.id for n in repo.get_answers_owed_for_persona( _PERSONA, max_age_hours=None ) }
    assert id_25h not in capped_ids,   "25h-created row must be EXCLUDED by the 24h age cap (cap on created_at)"
    assert id_25h in uncapped_ids,     "25h-created row must be PRESENT uncapped (proves the cap, not a filter bug)"

    # ── D-V4: a 20h-created ask answered 2min ago still delivers; cursor on responded_at ──
    id_old = _add_notif( session, rid, responded_ago=timedelta( minutes=2 ), created_ago_hours=20, message="20h old, fresh answer" )
    session.commit()
    assert id_old in { n.id for n in repo.get_answers_owed_for_persona( _PERSONA, max_age_hours=24 ) }, (
        "20h-created ask answered 2min ago must DELIVER (cursor/order on responded_at, not created_at)"
    )
    now = datetime.now( timezone.utc )
    since_before = { n.id for n in repo.get_answers_owed_for_persona( _PERSONA, since=now - timedelta( minutes=10 ) ) }
    since_after  = { n.id for n in repo.get_answers_owed_for_persona( _PERSONA, since=now + timedelta( minutes=10 ) ) }
    assert id_old in since_before, "since just BEFORE the answer time must include the row (cursor on responded_at)"
    assert id_old not in since_after, "since just AFTER the answer time must exclude the row (cursor on responded_at)"

    # ── Ordering: results are oldest-answer-first (responded_at asc) ────────────
    answered = repo.get_answers_owed_for_persona( _PERSONA, max_age_hours=None )
    resp_times = [ n.responded_at for n in answered ]
    assert resp_times == sorted( resp_times ), "results must be ordered by responded_at ascending"

    # ── Ack (ruling 2): mark removes from owed, row still exists ────────────────
    marked = repo.mark_answer_delivered( id_owed )
    session.commit()
    assert marked is not None and marked.answer_delivered_at is not None
    assert id_owed not in { n.id for n in repo.get_answers_owed_for_persona( _PERSONA, max_age_hours=None ) }, (
        "after mark_answer_delivered the row leaves the owed set"
    )
    assert repo.get_by_id( id_owed ) is not None, "ruling 2: the row is NEVER deleted, only marked"


def test_mark_answer_delivered_stores_correct_instant_under_nonutc_session( owed_session ):
    """
    GUARD for the naive-utcnow finding (notification_repository.py:468).

    mark_answer_delivered must store the correct ABSOLUTE instant regardless of the
    DB session's timezone. A naive datetime.utcnow() written into a TIMESTAMPTZ
    column is interpreted in the session's TimeZone GUC, so on a NON-UTC session the
    stored instant is shifted by the offset — the audit trail records the wrong time.

    DIVERGENCE INPUT: a non-UTC session (America/New_York). A UTC-only assertion
    would NOT falsify the bug — Postgres returns TIMESTAMPTZ as tz-aware on readback
    regardless, and under UTC there is no offset to expose. We assert the stored
    absolute instant (EXTRACT(EPOCH ...), timezone-independent) matches real now.

    Expected: RED against the current naive utcnow() (off by the ~4-5h NY offset);
    GREEN once the fix lands datetime.now(timezone.utc). This guard is meant to land
    WITH that fix so the one-liner is never left unprotected (María, 2026-08-01).
    """
    session = owed_session
    repo    = NotificationRepository( session )
    rid     = _make_user( session )
    nid     = _add_notif( session, rid, responded_ago=timedelta( minutes=2 ), message="tz guard" )
    session.commit()

    session.execute( text( "SET TIME ZONE 'America/New_York'" ) )
    try:
        t0 = time.time()
        repo.mark_answer_delivered( nid )
        session.commit()
        epoch_stored = session.execute(
            text( "SELECT EXTRACT( EPOCH FROM answer_delivered_at ) FROM notifications WHERE id = :nid" ),
            { "nid": str( nid ) },
        ).scalar()
    finally:
        session.execute( text( "SET TIME ZONE 'UTC'" ) )
        session.commit()

    assert epoch_stored is not None, "answer_delivered_at must be set after mark"
    drift = abs( float( epoch_stored ) - t0 )
    assert drift < 120, (
        f"stored instant is off by {drift:.0f}s under a non-UTC session — naive utcnow() "
        f"was interpreted in the session timezone. Use datetime.now( timezone.utc )."
    )



# ─────────────────────────────────────────────────────────────────────────────
# Row 3b4002fe — the SIBLINGS of the guarded line.
#
# The guard above proves ONE line (notification_repository.py:468, the aware
# mark_answer_delivered). Its own comment names `responded_at` as the thing to
# stay consistent WITH — and responded_at was still naive, in two places, with
# no guard at all. delivered_at and last_login_at were naive too. A green guard
# covering one line while three siblings carry the identical defect reads as
# coverage it does not have.
#
# Each guard below is the same shape as María's: write under a non-UTC session,
# read the stored ABSOLUTE instant with EXTRACT( EPOCH ... ) — which is
# timezone-independent — and require it to match real wall-clock now. A UTC-only
# assertion cannot falsify the bug: TIMESTAMPTZ reads back aware either way, and
# under UTC there is no offset to expose.
# ─────────────────────────────────────────────────────────────────────────────

_NON_UTC_ZONE = "America/New_York"


def _stored_epoch( session, table, column, row_id ):
    """Read one timestamp column back as a timezone-independent epoch."""
    return session.execute(
        text( f"SELECT EXTRACT( EPOCH FROM {column} ) FROM {table} WHERE id = :rid" ),
        { "rid": str( row_id ) },
    ).scalar()


def _assert_instant_is_right( epoch_stored, t0, column ):
    assert epoch_stored is not None, f"{column} must be set"
    drift = abs( float( epoch_stored ) - t0 )
    assert drift < 120, (
        f"{column} is off by {drift:.0f}s under a {_NON_UTC_ZONE} session — a naive "
        f"utcnow() was interpreted in the session timezone. Use datetime.now( timezone.utc )."
    )


def test_update_state_delivered_stores_correct_instant_under_nonutc_session( owed_session ):
    """GUARD: NotificationRepository.update_state writes delivered_at (naive utcnow, :401)."""
    session = owed_session
    repo    = NotificationRepository( session )
    rid     = _make_user( session )
    nid     = _add_notif( session, rid, message="tz guard delivered_at" )
    session.commit()

    session.execute( text( f"SET TIME ZONE '{_NON_UTC_ZONE}'" ) )
    try:
        t0 = time.time()
        repo.update_state( nid, "delivered" )
        session.commit()
        epoch_stored = _stored_epoch( session, "notifications", "delivered_at", nid )
    finally:
        session.execute( text( "SET TIME ZONE 'UTC'" ) )
        session.commit()

    _assert_instant_is_right( epoch_stored, t0, "delivered_at" )


def test_update_state_responded_stores_correct_instant_under_nonutc_session( owed_session ):
    """GUARD: NotificationRepository.update_state writes responded_at (naive utcnow, :401)."""
    session = owed_session
    repo    = NotificationRepository( session )
    rid     = _make_user( session )
    nid     = _add_notif( session, rid, message="tz guard responded_at via update_state" )
    session.commit()

    session.execute( text( f"SET TIME ZONE '{_NON_UTC_ZONE}'" ) )
    try:
        t0 = time.time()
        repo.update_state( nid, "responded" )
        session.commit()
        epoch_stored = _stored_epoch( session, "notifications", "responded_at", nid )
    finally:
        session.execute( text( "SET TIME ZONE 'UTC'" ) )
        session.commit()

    _assert_instant_is_right( epoch_stored, t0, "responded_at" )


def test_update_response_stores_correct_instant_under_nonutc_session( owed_session ):
    """GUARD: NotificationRepository.update_response writes responded_at (naive utcnow, :437)."""
    session = owed_session
    repo    = NotificationRepository( session )
    rid     = _make_user( session )
    nid     = _add_notif( session, rid, message="tz guard responded_at via update_response" )
    session.commit()

    session.execute( text( f"SET TIME ZONE '{_NON_UTC_ZONE}'" ) )
    try:
        t0 = time.time()
        repo.update_response( nid, { "answer": "yes" } )
        session.commit()
        epoch_stored = _stored_epoch( session, "notifications", "responded_at", nid )
    finally:
        session.execute( text( "SET TIME ZONE 'UTC'" ) )
        session.commit()

    _assert_instant_is_right( epoch_stored, t0, "responded_at" )


def test_update_last_login_stores_correct_instant_under_nonutc_session( owed_session ):
    """GUARD: UserRepository.update_last_login writes last_login_at (naive utcnow, :134)."""
    session   = owed_session
    user_repo = UserRepository( session )
    rid       = _make_user( session )
    session.commit()

    session.execute( text( f"SET TIME ZONE '{_NON_UTC_ZONE}'" ) )
    try:
        t0 = time.time()
        user_repo.update_last_login( rid )
        session.commit()
        epoch_stored = _stored_epoch( session, "users", "last_login_at", rid )
    finally:
        session.execute( text( "SET TIME ZONE 'UTC'" ) )
        session.commit()

    _assert_instant_is_right( epoch_stored, t0, "last_login_at" )



# ─────────────────────────────────────────────────────────────────────────────
# THE EXPIRY PAIR — two wrongs that may be cancelling (Cheech, row 3b4002fe).
#
# routers/notifications.py:522 WRITES expires_at as a naive utcnow() + timeout,
# and notification_repository.py:679 SWEEPS by comparing a naive now against that
# same TIMESTAMPTZ column. Both sides are interpreted in the session's TimeZone
# GUC, so when write and sweep happen under the SAME session the two shifts
# cancel and the sweep looks correct.
#
# ⇒ FIXING EITHER SIDE ALONE TURNS A CANCELLING PAIR INTO A LIVE ONE-SIDED BUG.
#   The pair below pins both halves of that: same-session behaviour (which is
#   green today, and green for the wrong reason) and cross-session behaviour
#   (which is broken today and is what a real deployment eventually looks like).
# ─────────────────────────────────────────────────────────────────────────────

def _add_expiring_notif( session, recipient_id, expires_at, *, message ):
    """One delivered notification whose expires_at is written as the caller supplies it."""
    nid = uuid.uuid4()
    session.add( Notification(
        id                 = nid,
        sender_id          = f"claude.code@lupin.deepily.ai#{_PERSONA}sess",
        recipient_id       = recipient_id,
        message            = message,
        type               = "task",
        priority           = "high",
        created_at         = datetime.now( timezone.utc ) - timedelta( hours=1 ),
        sender_persona     = _PERSONA,
        response_requested = True,
        state              = "delivered",
        expires_at         = expires_at,
    ) )
    session.flush()
    return nid


def _sweep_ids( repo ):
    return { n.id for n in repo.get_expired_notifications() }


def test_expiry_sweep_same_session_timezone( owed_session ):
    """The cancelling case: write AND sweep under the same non-UTC session.

    An expires_at 60s in the PAST must be swept. Today this passes — but it
    passes because the write shift and the sweep shift are equal and opposite,
    not because either is right. If this ever goes red after only ONE half of
    the pair is fixed, that is the cancellation breaking, not a new defect.
    """
    session = owed_session
    repo    = NotificationRepository( session )
    rid     = _make_user( session )

    session.execute( text( f"SET TIME ZONE '{_NON_UTC_ZONE}'" ) )
    try:
        # written exactly the way routers/notifications.py:522 writes it
        naive_past = datetime.utcnow() - timedelta( seconds=60 )
        nid = _add_expiring_notif( session, rid, naive_past, message="expiry same-session" )
        session.commit()
        swept = _sweep_ids( repo )
    finally:
        session.execute( text( "SET TIME ZONE 'UTC'" ) )
        session.commit()

    assert nid in swept, (
        "a notification that expired 60s ago was NOT swept under a same-timezone "
        "session — the write/sweep shifts no longer cancel"
    )


def test_expiry_sweep_across_session_timezones( owed_session ):
    """The real case: write under one session timezone, sweep under another.

    Nothing cancels here. An expires_at 60s in the past is stored 4h in the
    FUTURE by the non-UTC write, so the UTC sweep does not see it as expired and
    the notification never times out. RED against the current naive pair; GREEN
    once BOTH halves are aware.
    """
    session = owed_session
    repo    = NotificationRepository( session )
    rid     = _make_user( session )

    session.execute( text( f"SET TIME ZONE '{_NON_UTC_ZONE}'" ) )
    try:
        naive_past = datetime.utcnow() - timedelta( seconds=60 )
        nid = _add_expiring_notif( session, rid, naive_past, message="expiry cross-session" )
        session.commit()
    finally:
        session.execute( text( "SET TIME ZONE 'UTC'" ) )
        session.commit()

    # …and sweep from a UTC session, as a different worker or a restarted
    # process would.
    swept = _sweep_ids( repo )

    assert nid in swept, (
        "a notification that expired 60s ago was NOT swept when the sweep ran under "
        "a different session timezone than the write — the naive write stored the "
        "instant 4h in the future, so it will not time out for another 4h"
    )
