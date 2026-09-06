"""
The scan-then-mark race, reproduced — and the guard that closes it, proven to
refuse AND to write. Store row `bf4f65c3` (P1).

THE DEFECT. `NotificationRepository.mark_expired` read the row and wrote it in
two steps. Both writers of that row do this, in SEPARATE sessions: the orphan
sweeper (`notification_expiry_sweeper.py`) and the SSE timeout path
(`routers/notifications.py:572`). A `/respond` landing between another caller's
read and its write was overwritten — the row kept the human's `response_value`
and had its state stamped 'expired' anyway, so it carried a real answer while
claiming nobody had given one.

WHY THIS IS AN INTEGRATION TEST AND NOT A UNIT ONE. The whole finding lives in
what TWO SESSIONS see of ONE row, which is a property of the database and of
SQLAlchemy's identity map. A mocked session or a fake repo has neither, and the
sweeper's existing seam test — which uses a fake repo — stays green through the
entire defect. This enters at the layer the defect enters at.

WHAT THE FOUR ARMS ESTABLISH, and none of them is redundant:

  N  THE NEGATIVE CONTROL, and the reason the fix is a WHERE clause. The
     obvious guard is `if notification.state == expected`. Arm N shows that
     would have PASSED and clobbered anyway: in the sweeper's own session, at
     the same instant, `get_by_id().state` returns the value the object carried
     when that session last loaded it, while raw SQL returns the truth. Without
     this arm, arms B and C look like an elaborate way to write an `if`.

  A  THE DEFECT ITSELF, reproduced rather than derived. Drives the UNGUARDED
     call and observes state='expired' on a row carrying a real answer.

  B  THE GUARD REFUSES when a peer answered first.

  C  THE POSITIVE CONTROL — the guard WRITES when nobody raced. Arm B alone is
     equally consistent with a guard that refuses unconditionally, and a
     sweeper that never sweeps anything would satisfy it.

  N2 A FRESH session's read is NOT stale. Without this, arm N is equally
     consistent with "the peer's commit is invisible to any reader", which
     would make the finding about transactions rather than about the ORM.

  N3 WHICH READ FORMS ARE ACTUALLY SAFE — the arm that says what a reader
     should DO, and the one that reversed its own author. It was written to
     show that a `SELECT ... FOR UPDATE` refreshes a held object. It does NOT.
     The lock is real and the refresh is not: FOR UPDATE serializes the row at
     the database and leaves the Python attributes of an object the session
     already holds exactly as they were.

     That matters beyond this file, because a locked read is the remedy a
     reviewer reaches for first, and `TaskRepository.get_by_id_for_update` is
     that shape. It is correct in its stated usage — its caller's transaction
     is fresh — but the freshness comes from the CALLER, never from the lock.

SAY THE MECHANISM PRECISELY, because the narrow version lets a reader off. The
stale value is not "the scan-time state" as such — it is the state the object
carried when THAT SESSION last loaded it. Scan time is merely when that happens
to be, for the sweeper. A caller who does not scan is not thereby safe.

AND THE PRECONDITION IS WORTH STATING PRECISELY, because the loose version is
wrong. It is not "a session that once loaded the row" — it is a session STILL
HOLDING A LIVE REFERENCE to the loaded object. SQLAlchemy's identity map is
WEAK: drop the reference and the object is collected, and the next read goes to
the database and comes back fresh.

Measured, and it cost two red arms to learn: N2 and N3 failed on their first run
because they discarded the scan result, which made a genuinely exposed session
look safe. Both now BIND it, and both assert the row was scanned — an arm that
silently measures an empty population is the failure this whole file is about.

The sweeper binds its candidates for the length of the loop, so it IS exposed.
A fresh session, a `SELECT ... FOR UPDATE`, or an explicit refresh each close it,
which is why the promotion-ticket resolver reached the same invariant from the
other end and has no exposure here.

VENUE — :7999-eligible (AI-discretionary): a self-cleaning, pid-scoped throwaway
database on the dev Postgres server. It mutates nothing that outlives the run,
needs no server monopoly, takes seconds, and SKIPS when Postgres is unreachable.

AND IT IS IN `smoke/` RATHER THAN `integration/` FOR A REASON WORTH STATING,
because "it needs a real database" sounds like an integration test. The
integration tier carries a session-scoped autouse fixture that demands a LIVE
:8000 server running the Testing config block — a sound guard for that tier, and
an irrelevant one here: this file talks to Postgres directly and never touches a
server at all. Filed there it would have been gated on something it does not use,
and would run only when somebody stood up :8000. The throwaway-DB roundtrips
already living in `smoke/` are the precedent.

Authored by Pocholo 📣, 2026-09-06, on Mr. Radio 🦉's ruling that a mechanism
claim owes a run rather than a paragraph.
"""
import os
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


_THROWAWAY_DB = f"mark_expired_race_{os.getpid()}"
_THE_ANSWER   = { "value": "yes", "source": "ui" }


def _server_url():
    db_module.swap_database( "testing" )
    return db_module.engine.url


def _maintenance_engine( server_url ):
    return create_engine( server_url, isolation_level="AUTOCOMMIT" )


@pytest.fixture( scope="module" )
def race_sessions():
    """
    Throwaway DB -> `alembic upgrade head` -> yield a sessionmaker.

    Requires:
        - a reachable Postgres server at the testing URL

    Ensures:
        - yields a sessionmaker bound to a database nothing else uses
        - drops that database on teardown, terminating stragglers first
        - SKIPS the module rather than failing when Postgres is unreachable

    A FACTORY, not a session: every arm here needs TWO independent sessions on
    the same row, and handing out one shared session would collapse the very
    distinction under test.
    """
    server_url = _server_url()
    try:
        eng = _maintenance_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
            conn.execute( text( f'CREATE DATABASE "{_THROWAWAY_DB}"' ) )
        eng.dispose()
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable — skipping the mark_expired race proof: {e}" )

    throwaway_url = server_url.set( database=_THROWAWAY_DB ).render_as_string( hide_password=False )
    command.upgrade( build_alembic_config( database_url=throwaway_url ), "head" )

    engine  = create_engine( throwaway_url )
    Session = sessionmaker( bind=engine )
    try:
        yield Session
    finally:
        engine.dispose()
        eng = _maintenance_engine( server_url )
        with eng.connect() as conn:
            conn.execute( text(
                "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ), { "db": _THROWAWAY_DB } )
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
        eng.dispose()


@pytest.fixture( scope="module" )
def recipient_id( race_sessions ):
    """One user to hang every probe row off — the notifications FK needs a real one."""
    uid = uuid.uuid4()
    with race_sessions() as s:
        s.add( User(
            id             = uid,
            email          = f"race-{uid.hex[:8]}@test.local",
            password_hash  = "x",
            email_verified = True,
            is_active      = True,
            is_protected   = False,
            roles          = { "roles": [ "user" ] },
            created_at     = datetime.now( timezone.utc ),
        ) )
        s.commit()
    return uid


def _make_orphaned_ask( Session, recipient_id ):
    """
    One row the sweeper is entitled to close: delivered, response-required, and
    two days past its expiry. Returns its id.
    """
    nid = uuid.uuid4()
    with Session() as s:
        s.add( Notification(
            id                 = nid,
            sender_id          = "claude.code@lupin.deepily.ai#racesess",
            recipient_id       = recipient_id,
            message            = "race probe",
            type               = "custom",
            priority           = "medium",
            state              = "delivered",
            response_requested = True,
            response_default   = "no",
            expires_at         = datetime.now( timezone.utc ) - timedelta( days=2 ),
        ) )
        s.commit()
    return nid


def _a_human_answers( Session, notification_id ):
    """
    The /respond path, in its OWN session and COMMITTED — which is what makes
    this a race rather than two writes inside one transaction.
    """
    with Session() as s:
        NotificationRepository( s ).update_response( notification_id, _THE_ANSWER )
        s.commit()


def _committed_row( Session, notification_id ):
    """The truth, read fresh, in a session that never held this object."""
    with Session() as s:
        return s.execute(
            text( "SELECT state, response_value FROM notifications WHERE id = :i" ),
            { "i": str( notification_id ) }
        ).one()


def test_a_re_read_returns_the_state_the_session_last_loaded( race_sessions, recipient_id ):
    """
    ARM N — the negative control, and the whole argument for a WHERE clause.

    The sweeper loads its candidates in ONE session, so the row sits in that
    session's identity map. `BaseRepository.get_by_id` is
    `query().filter().first()`, which SQLAlchemy serves from the identity map
    without refreshing. So a re-read guard compares against a value that is
    already stale, and passes on a row that has been answered.

    Asserted against raw SQL in the SAME session, so the two readings differ by
    the ORM layer alone — not by transaction, connection or moment.
    """
    nid = _make_orphaned_ask( race_sessions, recipient_id )

    with race_sessions() as sweeper:
        repo    = NotificationRepository( sweeper )
        scanned = repo.get_expired_notifications()

        at_scan = [ n.state for n in scanned if n.id == nid ]
        assert at_scan == [ "delivered" ], (
            f"the probe row was not returned by the live scan (got {at_scan}) — this arm would be "
            "measuring an empty population rather than the identity map"
        )

        _a_human_answers( race_sessions, nid )

        re_read  = repo.get_by_id( nid ).state
        raw_same = sweeper.execute(
            text( "SELECT state FROM notifications WHERE id = :i" ), { "i": str( nid ) }
        ).scalar()

    assert raw_same == "responded", (
        f"raw SQL in the sweeper's own session sees '{raw_same}', so the peer's commit is not "
        "visible there at all and this arm cannot speak to the identity map"
    )
    assert re_read == "delivered", (
        f"the ORM re-read returned '{re_read}', not the stale 'delivered'. If SQLAlchemy has "
        "started refreshing here, a re-read guard would now be sound — but the WHERE-clause guard "
        "is still the one correct by construction. Re-derive before changing it."
    )


def test_the_unguarded_mark_stamps_expired_over_a_real_human_answer( race_sessions, recipient_id ):
    """
    ARM A — the defect, reproduced.

    Drives the UNGUARDED call (expected_state left at its default) after a
    committed answer, and observes the inconsistent row: state 'expired',
    response_value still carrying what the human said.

    This arm must keep passing. It is not a museum piece describing old
    behaviour — it pins that the DEFAULT path is still unconditional, which is
    what keeps every pre-existing caller byte-unchanged.
    """
    nid = _make_orphaned_ask( race_sessions, recipient_id )

    with race_sessions() as sweeper:
        repo = NotificationRepository( sweeper )
        repo.get_expired_notifications()
        _a_human_answers( race_sessions, nid )
        returned = repo.mark_expired( nid, apply_default=False )
        sweeper.commit()

    state, response_value = _committed_row( race_sessions, nid )

    assert returned is not None,          "the unguarded call refused, which it must never do"
    assert state == "expired",            f"unguarded mark left state '{state}'"
    assert response_value == _THE_ANSWER, (
        f"the human's answer did not survive the overwrite (got {response_value}) — the defect is "
        "an INCONSISTENT row, not a lost answer, and the row body says so"
    )


def test_the_guarded_mark_refuses_when_the_row_stopped_being_delivered( race_sessions, recipient_id ):
    """
    ARM B — the guard refuses. Same setup as arm A, one variable changed.
    """
    nid = _make_orphaned_ask( race_sessions, recipient_id )

    with race_sessions() as sweeper:
        repo = NotificationRepository( sweeper )
        repo.get_expired_notifications()
        _a_human_answers( race_sessions, nid )
        returned = repo.mark_expired( nid, apply_default=False, expected_state="delivered" )
        sweeper.commit()

    state, response_value = _committed_row( race_sessions, nid )

    assert returned is None, "the guard returned a row, so it wrote when it should have refused"
    assert state == "responded", (
        f"the row is '{state}' — either the guard refused in Python and something still wrote, or "
        "the answer never landed"
    )
    assert response_value == _THE_ANSWER


def test_the_guarded_mark_still_writes_when_nobody_raced( race_sessions, recipient_id ):
    """
    ARM C — the positive control.

    Without this, arm B is equally satisfied by a guard that refuses every time,
    and a sweeper that never sweeps anything would pass the suite.
    """
    nid = _make_orphaned_ask( race_sessions, recipient_id )

    with race_sessions() as sweeper:
        repo = NotificationRepository( sweeper )
        repo.get_expired_notifications()
        returned = repo.mark_expired( nid, apply_default=False, expected_state="delivered" )
        sweeper.commit()

    state, response_value = _committed_row( race_sessions, nid )

    assert returned is not None, (
        "the guard refused a row nobody touched — it is a permanent no rather than a guard, and "
        "arm B then proves nothing"
    )
    assert state == "expired"
    assert response_value is None, (
        f"apply_default=False still wrote a response_value ({response_value}) — the sweeper must "
        "never assert an answer that reached nobody"
    )


def test_a_fresh_session_reads_the_truth( race_sessions, recipient_id ):
    """
    ARM N2 — the first closure, and the control that stops arm N from being
    read as a claim about transactions.

    Arm N shows an ORM re-read going stale in a session that already loaded the
    row. That result is ALSO consistent with the peer's commit simply not being
    visible to anyone — which would be a story about isolation levels, not about
    the identity map. This arm rules that out: a session that never held the
    object sees the answer immediately.
    """
    nid = _make_orphaned_ask( race_sessions, recipient_id )

    with race_sessions() as first:
        # BIND the scan result. SQLAlchemy's identity map holds WEAK references,
        # so an unbound result is collected and the next read goes to the
        # database — which looks exactly like the staleness having gone away.
        # Measured 2026-09-06: this arm failed on its first run for precisely
        # that reason. The sweeper binds its candidates, so it IS exposed.
        candidates = NotificationRepository( first ).get_expired_notifications()
        assert any( n.id == nid for n in candidates ), "the probe row was not scanned"

        _a_human_answers( race_sessions, nid )

        with race_sessions() as fresh:
            fresh_read = NotificationRepository( fresh ).get_by_id( nid ).state

        stale_read = NotificationRepository( first ).get_by_id( nid ).state

    assert fresh_read == "responded", (
        f"a session that never held this row read '{fresh_read}' — the peer's commit is not "
        "visible to ANY reader, so arm N is about isolation and not about the identity map"
    )
    assert stale_read == "delivered", (
        f"the holding session read '{stale_read}' — if it now agrees with the fresh one, the "
        "identity-map finding has changed and arm N should be re-derived"
    )


def test_only_an_explicit_refresh_makes_a_held_object_fresh( race_sessions, recipient_id ):
    """
    ARM N3 — the remedy census, and it is a census of ALL SIX forms rather than
    a claim about one, because the wrong three are the ones a reviewer suggests.

    Measured 2026-09-06, SQLAlchemy 2.0.40, real Postgres, one session holding a
    LIVE reference to the loaded object while a peer commits:

        get_by_id (query.filter.first)      STALE
        session.get( with_for_update=True ) STALE
        query.with_for_update().first()     STALE
        query.populate_existing().first()   fresh
        session.refresh() then read         fresh
        raw SQL in the same session         fresh

    THE LOCK IS REAL AND THE REFRESH IS NOT. `FOR UPDATE` serializes the row at
    the database — that part of every for-update docstring in this repo is
    true — but it does not repopulate the attributes of an object the identity
    map already holds. Only `populate_existing()`, an explicit `refresh()`, or
    going round the ORM entirely will do that.

    This arm exists because the author asserted the opposite from the
    SQLAlchemy contract, told two peers, and was corrected by his own run.
    """
    forms = {}

    for name in (
        "get_by_id",
        "session.get(with_for_update)",
        "query.with_for_update().first()",
        "query.populate_existing().first()",
        "session.refresh()",
        "raw SQL",
    ):
        nid = _make_orphaned_ask( race_sessions, recipient_id )

        with race_sessions() as holder:
            # BOUND — see arm N2 on weak references.
            candidates = NotificationRepository( holder ).get_expired_notifications()
            assert any( n.id == nid for n in candidates ), f"{name}: the probe row was not scanned"

            _a_human_answers( race_sessions, nid )

            if   name == "get_by_id":
                got = NotificationRepository( holder ).get_by_id( nid ).state
            elif name == "session.get(with_for_update)":
                got = holder.get( Notification, nid, with_for_update=True ).state
            elif name == "query.with_for_update().first()":
                got = holder.query( Notification ).filter(
                    Notification.id == nid ).with_for_update().first().state
            elif name == "query.populate_existing().first()":
                got = holder.query( Notification ).filter(
                    Notification.id == nid ).populate_existing().first().state
            elif name == "session.refresh()":
                held = holder.get( Notification, nid )
                holder.refresh( held )
                got = held.state
            else:
                got = holder.execute(
                    text( "SELECT state FROM notifications WHERE id = :i" ), { "i": str( nid ) }
                ).scalar()

            holder.rollback()

        forms[ name ] = got

    stale = sorted( n for n, v in forms.items() if v == "delivered" )
    fresh = sorted( n for n, v in forms.items() if v == "responded" )

    assert not ( set( stale ) & set( fresh ) ), f"a form reported both ways: {forms}"
    assert len( stale ) + len( fresh ) == 6, (
        f"a form returned something that is neither state — the fixture is wrong, not the ORM: {forms}"
    )

    assert stale == [
        "get_by_id",
        "query.with_for_update().first()",
        "session.get(with_for_update)",
    ], (
        f"the STALE set moved: {forms}. If a for-update form has started refreshing, then a "
        "locked read is now self-sufficient and every docstring in this repo that credits the "
        "lock for freshness can stop leaning on its caller. Re-derive before relying on it."
    )

    assert fresh == [
        "query.populate_existing().first()",
        "raw SQL",
        "session.refresh()",
    ], (
        f"the FRESH set moved: {forms}. These three are the only remedies this file endorses for a "
        "session that still holds the row; if one stopped working, callers relying on it are exposed."
    )
