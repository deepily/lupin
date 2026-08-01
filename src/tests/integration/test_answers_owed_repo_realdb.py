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
