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


def _still_holds( session, notification_id ):
    """
    Is the row still in this session's identity map?

    The precondition for the whole finding is a session STILL HOLDING A LIVE
    REFERENCE — the identity map is WEAK, so a scan whose result is discarded
    leaves nothing behind and the next read comes back fresh. An arm that means
    to exercise the exposure must assert this, or it silently measures a fresh
    session and reports a green that says less than it looks.

    Measured 2026-09-06 at 8721c4fb, which is why arms B and C now bind:
    discarding the scan result gives False here (with or without an explicit
    gc.collect()), while the sweeper's own bound shape gives True.
    """
    return any( getattr( o, "id", None ) == notification_id
                for o in session.identity_map.values() )


def _committed_row( Session, notification_id ):
    """The truth, read fresh, in a session that never held this object."""
    with Session() as s:
        return s.execute(
            text( "SELECT state, response_value FROM notifications WHERE id = :i" ),
            { "i": str( notification_id ) }
        ).one()


def test_the_exposure_check_itself_can_tell_the_two_cases_apart( race_sessions, recipient_id ):
    """
    THE GUARD ON THE GUARD. `_still_holds` is what arms B, C and D lean on to
    claim their session is genuinely exposed. Neuter it to `return True` and
    every one of them stays green — measured 2026-09-06, 8 passed — so without
    this test the helper is UNGUARDED: correct today, and nothing would fire
    the day it stopped being.

    Both directions, one variable, because "it returns True" and "it returns
    True WHEN IT SHOULD" are different claims and a helper hardcoded to True
    satisfies the first.
    """
    nid = _make_orphaned_ask( race_sessions, recipient_id )

    with race_sessions() as discarding:
        NotificationRepository( discarding ).get_expired_notifications()   # result DISCARDED
        assert not _still_holds( discarding, nid ), (
            "the identity map still holds a row whose scan result was discarded. Either it "
            "stopped being weak, or this helper is answering a different question than it "
            "claims — and arms B, C and D all rest on the answer"
        )

    with race_sessions() as binding:
        candidates = NotificationRepository( binding ).get_expired_notifications()   # BOUND
        assert _still_holds( binding, nid ), (
            "the helper cannot see a row this session demonstrably holds — it is blind, and "
            "every arm asserting exposure through it is asserting nothing"
        )
        assert any( n.id == nid for n in candidates ), (
            "the scan did not reach the row, so this arm measured an empty population — the "
            "failure this whole file is about"
        )


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
        repo       = NotificationRepository( sweeper )
        candidates = repo.get_expired_notifications()          # BOUND — see _still_holds
        assert _still_holds( sweeper, nid ), (
            "this arm discarded the scan result, so the row left the identity map and the "
            "session is effectively FRESH — it would demonstrate the guard refusing a session "
            "that was never exposed, which is not what this file claims"
        )
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
        repo       = NotificationRepository( sweeper )
        candidates = repo.get_expired_notifications()          # BOUND, as arm B is
        assert _still_holds( sweeper, nid ), (
            "the control must start from the SAME exposed state as arm B, or the pair varies "
            "two things at once and neither arm isolates the guard"
        )
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


# ---------------------------------------------------------------------------
# ARMS D / Dc — the sweeper's OWN path, entered at sweep_once, on a session a
# caller handed it ALREADY DIRTY.
#
# WHY THESE EXIST, AND WHY THE ARMS ABOVE DO NOT COVER THEM. Arms B and C call
# `mark_expired` directly, which establishes what the WHERE clause does and
# says nothing about whether the sweeper's own path REACHES it. The question
# these close is the one asked six times of this branch and never answered on
# the code: `sweep_once` takes an INJECTABLE `session_factory`, so a caller can
# hand it a session that has already loaded the row and still holds it — the
# same seam that makes the promotion resolver's `db_fn` an unguarded
# precondition. If this path were safe by CALLER FRESHNESS the way that one is,
# this injection would remove its only sufficient leg and it would clobber.
#
# 🔴 A FIRST CUT OF ARM D DID NOT TEST THIS AND LOOKED LIKE IT DID. Injecting a
# dirty session and letting the peer answer BEFORE `sweep_once` ran produced
# swept=0 refused=0 and a row still carrying its answer — green, and measuring
# a different mechanism. `sweep_once` re-scans in SQL, so a row answered before
# the scan is simply not in `get_expired_notifications()`'s result and the
# WHERE clause is never reached. That is correct behaviour and it is not this
# race. The race has to fire BETWEEN the scan and the mark, which is what
# wrapping `_partition` buys: it runs after the one and before the other, and
# wrapping it chooses the moment without altering the code under test.
#
# Measured 2026-09-06 at 23782c08: both arms below, plus the dirty-session
# control, plus the answered-before-scan case, 35 assertions 0 failed.
# ---------------------------------------------------------------------------

def _sweep_racing_at_the_seam( monkeypatch, factory, on_scan=None ):
    """
    Run one sweep pass, optionally firing `on_scan` between the scan and the mark.

    Requires:
        - factory is a context manager yielding a DB session
        - on_scan is a zero-arg callable, or None for an unraced pass

    Ensures:
        - returns ( result_dict, times_the_race_fired )
        - fires on_scan AT MOST once, after get_expired_notifications() has
          returned and before the mark loop begins
        - restores the real _partition even when the pass raises
    """
    from cosa.rest import notification_expiry_sweeper as sweeper

    real  = sweeper._partition
    fired = { "n": 0 }

    def racing_partition( candidates, grace_seconds, now ):
        out = real( candidates, grace_seconds, now )
        if on_scan is not None and not fired[ "n" ]:
            fired[ "n" ] = 1
            on_scan()
        return out

    monkeypatch.setattr( sweeper, "_partition", racing_partition )
    return sweeper.sweep_once( factory, grace_seconds=0 ), fired[ "n" ]


def _dirty_factory( Session, notification_id ):
    """
    A session that has ALREADY scanned the row and STILL HOLDS it, wrapped as a
    factory — the exposure `sweep_once`'s injectable seam permits.

    Returns ( factory, session, what_the_identity_map_serves ). The held object
    is BOUND deliberately: the identity map is WEAK, and an arm that discards
    the scan result makes a genuinely exposed session look safe.
    """
    from contextlib import contextmanager

    session = Session()
    scanned = [ n for n in NotificationRepository( session ).get_expired_notifications()
                if n.id == notification_id ]
    assert scanned, "the scan did not reach the row — this arm would measure an empty population"
    held = scanned[ 0 ]

    @contextmanager
    def factory():
        yield session

    return factory, session, held


def test_the_sweeper_refuses_even_when_its_session_was_handed_to_it_dirty(
    race_sessions, recipient_id, monkeypatch
):
    """
    ARM D — the sweeper is safe by CONSTRUCTION, not by caller freshness.
    """
    nid                     = _make_orphaned_ask( race_sessions, recipient_id )
    factory, session, held  = _dirty_factory( race_sessions, nid )

    before_sweep = held.state

    result, fired = _sweep_racing_at_the_seam(
        monkeypatch, factory, on_scan=lambda: _a_human_answers( race_sessions, nid )
    )
    # Read the held object BEFORE closing its session: after close every
    # attribute raises DetachedInstanceError, which reads as a broken test
    # rather than as the staleness this arm exists to demonstrate.
    after_sweep = held.state
    session.commit()
    session.close()

    state, response_value = _committed_row( race_sessions, nid )

    assert fired == 1, "the race never fired, so this arm did not exercise the seam it names"
    assert before_sweep == "delivered"
    assert after_sweep == "delivered", (
        f"the held object reads '{after_sweep}' — the identity map is NOT stale at the moment the "
        "guard ran, so this arm is not exercising the exposure it was written for and its green "
        "means nothing"
    )
    # SCOPED TO THIS ROW, NOT TO THE PASS. sweep_once closes every eligible row in
    # the database, so `swept == 0` was a claim about the whole population and any
    # other test leaving an unswept orphan behind broke this arm. Measured
    # 2026-09-06: adding one unrelated test above reddened it for exactly that
    # reason. The row-level assertions below are the ones that carry the finding,
    # and `refused >= 1` still kills the counter mutation because this row
    # contributes exactly one refusal.
    assert result[ "refused" ] >= 1, (
        f"refused={result['refused']} — the guard refused this row but the pass did not count "
        "it, which is the one number that would tell anyone this race is live"
    )
    assert state == "responded"
    assert response_value == _THE_ANSWER


def test_the_sweeper_still_sweeps_on_that_same_dirty_session(
    race_sessions, recipient_id, monkeypatch
):
    """
    ARM Dc — the positive control, on the SAME dirty session.

    Without it, arm D is equally satisfied by a sweeper that refuses everything
    whenever its session is dirty, which would be a different defect wearing
    arm D's green.
    """
    nid                     = _make_orphaned_ask( race_sessions, recipient_id )
    factory, session, held  = _dirty_factory( race_sessions, nid )

    before_sweep = held.state

    result, fired = _sweep_racing_at_the_seam( monkeypatch, factory, on_scan=None )
    session.commit()
    session.close()

    state, response_value = _committed_row( race_sessions, nid )

    assert fired == 0
    # BEFORE the sweep, deliberately. A matched write carries
    # synchronize_session="fetch", which refreshes this very object, so a
    # post-sweep reading here would assert the OPPOSITE of arm D's and say
    # nothing about where this arm STARTED.
    assert before_sweep == "delivered", "the arm must start from the same exposed state as arm D"
    # SCOPED, for the reason given in arm D: these counts are the whole pass, not
    # this row. `state == 'expired'` below is what proves THIS row was written.
    assert result[ "swept" ] >= 1, (
        f"swept={result['swept']} on a row nobody raced — the sweeper refuses whenever its session "
        "is dirty, so arm D proves nothing"
    )
    assert state == "expired"
    assert response_value is None
