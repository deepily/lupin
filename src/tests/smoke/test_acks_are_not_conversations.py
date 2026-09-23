"""
A saved broadcast ack is not a CONVERSATION. Row 4f320c27 follow-up, on d0bd0c74.

THE DEFECT, and it is mine. b9136bcf excluded `commons_broadcast_ack` rows from the two
SENDER ROSTER queries. It did not touch the conversation reads — and saving acks put a
new row TYPE into a table those reads walk, so four endpoints began answering with rows
that are not messages.

Measured on a throwaway Postgres with EXACTLY ONE saved ack and no other notifications:

    get_active_conversation        -> 'claude.code@unknown.deepily.ai#f19a8996'
    get_sender_conversation        -> 1 row
    get_sender_conversations_by_date -> 1 date group
    get_sender_date_summaries      -> [{'date': '2026-09-23', 'count': 1, 'new_count': 0}]

🔴 WHY NOTHING CAUGHT IT, AND WHY THESE ASSERTIONS ARE DB-BACKED RATHER THAN RENDERED.
The multiplexer's `normalizeHistoryRow` rejects an empty message, so an ack row is
DROPPED AT RENDER. The rows are therefore invisible while the counts, the date buckets
and the active-conversation pick are all silently wrong. There is no failing behaviour
to see, and a UI test would go green over the whole defect. The only way to catch it is
to ask the query.

🔴 THE WORST OF THE FOUR IS `get_active_conversation`. It backs
`/api/notifications/active-conversation/{user_email}`, so a seat that merely ACKED a
broadcast can become the user's active conversation — a conversation with someone who
never said anything.

SCOPE — narrow, and the narrowness is deliberate. `count_by_sender` and
`get_by_recipient` also return the ack, but neither has a caller outside tests
(`grep -rn "\\.count_by_sender(" src/` is empty of live call sites), so they are left
alone rather than churned. Excluding everything everywhere would be the enumeration
habit the project warns about; the predicate is "reads that answer *show me the user's
conversations*", and these four are the ones with live callers.

WHAT STAYS UNCHANGED: `get_latest_acks_for_broadcast` has its own query and must still
return every ack. That is asserted here too, because a fix that hid acks from their own
endpoint would pass every other assertion in this file.

VENUE — :7999-eligible. Creates and DROPS its own uniquely-named throwaway database,
mutates nothing that outlives the test, needs no monopoly, runs in seconds, and SKIPS
rather than fails when Postgres is unreachable.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from alembic import command

import cosa.rest.commons_ack_watcher as watcher_module
from cosa.rest.commons_ack_watcher import CommonsAckWatcher
from cosa.rest.db import database as db_module
from cosa.rest.db.auto_migrate import build_alembic_config
from cosa.rest.db.repositories.notification_repository import NotificationRepository


_THROWAWAY_DB = f"acks_not_conversations_{os.getpid()}"

_BROADCAST_ID = "22222222-bbbb-4ccc-8ddd-333333333333"
_SESSION_ID   = "f19a8996-2fdc-425d-82bc-0e99f3cd8db2"
# The sender_id an ack is stamped with — see _ACK_SENDER_UNKNOWN_PROJECT. The
# conversation reads are keyed by sender_id, so the query has to be asked about THIS one.
_ACK_SENDER   = "claude.code@unknown.deepily.ai#f19a8996"
_REAL_SENDER  = "claude.code@lupin.deepily.ai#deadbeef"


def _server_url():
    """Borrow a credential-correct server URL; every write lands in the throwaway DB."""
    db_module.swap_database( "testing" )
    return db_module.engine.url


@pytest.fixture( scope="module" )
def throwaway_db_url():
    server_url = _server_url()
    try:
        eng = create_engine( server_url, isolation_level="AUTOCOMMIT" )
        with eng.connect() as conn:
            conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
            conn.execute( text( f'CREATE DATABASE "{_THROWAWAY_DB}"' ) )
        eng.dispose()
    except OperationalError as e:
        pytest.skip( f"Postgres unreachable — skipping the acks-are-not-conversations check: {e}" )

    url = server_url.set( database=_THROWAWAY_DB )
    command.upgrade( build_alembic_config( database_url=url.render_as_string( hide_password=False ) ), "head" )
    yield url

    eng = create_engine( server_url, isolation_level="AUTOCOMMIT" )
    with eng.connect() as conn:
        conn.execute( text(
            "SELECT pg_terminate_backend( pid ) FROM pg_stat_activity "
            "WHERE datname = :db AND pid <> pg_backend_pid()"
        ), { "db": _THROWAWAY_DB } )
        conn.execute( text( f'DROP DATABASE IF EXISTS "{_THROWAWAY_DB}"' ) )
    eng.dispose()


@pytest.fixture( scope="module" )
def engine( throwaway_db_url ):
    eng = create_engine( throwaway_db_url )
    yield eng
    eng.dispose()


@pytest.fixture
def recipient( engine ):
    """A real users row — notifications.recipient_id is a FK to it."""
    user_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text( "INSERT INTO users ( id, email, password_hash, created_at ) "
                  "VALUES ( :id, :email, :pw, now() )" ),
            { "id": str( user_id ), "email": f"ack-conv-{user_id}@example.invalid",
              "pw": "not-a-credential-throwaway-fixture" }
        )
    return user_id


@pytest.fixture
def db( engine, monkeypatch ):
    """Point the watcher's get_db at the throwaway database. A connection string, not behaviour."""
    Session = sessionmaker( bind=engine )

    class _Ctx:
        def __enter__( self ):
            self.session = Session()
            return self.session
        def __exit__( self, exc_type, *_ ):
            self.session.commit() if exc_type is None else self.session.rollback()
            self.session.close()
            return False

    monkeypatch.setattr( watcher_module, "get_db", lambda: _Ctx() )
    return Session


def _save_one_ack( recipient, db ):
    """Drive one ack through the REAL watcher, exactly as tick() would."""
    CommonsAckWatcher(
        store                = object(),
        push_notification_fn = lambda **kwargs: None,
    )._push_ack_event(
        { "sender_session_id" : _SESSION_ID,
          "persona_name"      : "Mr. Radio",
          "persona_icon"      : "🦉",
          "persona_color"     : "#FFA000" },
        _BROADCAST_ID, str( recipient ),
        { "status": "completed", "body_summary": "…" }
    )


def _repo( db ):
    return NotificationRepository( db() )


# ═══════════════════════════════════════════════════════════════════════════════
# The four reads with live endpoint callers
# ═══════════════════════════════════════════════════════════════════════════════

class TestASavedAckIsNotAConversation:
    """
    Every test here saves EXACTLY ONE ack and nothing else, so any non-empty answer
    below is the ack and nothing but the ack.
    """

    def test_an_acking_seat_is_not_the_ACTIVE_CONVERSATION( self, recipient, db ):
        """
        🔴 THE WORST OF THE FOUR. `/api/notifications/active-conversation/{email}` would
        open a conversation with a seat that never said anything — it only acked.
        """
        _save_one_ack( recipient, db )
        session = db()
        try:
            active = NotificationRepository( session ).get_active_conversation( recipient )
        finally:
            session.close()
        assert active is None, f"an ack must not become the active conversation, got {active!r}"

    def test_an_ack_is_not_a_message_in_a_conversation( self, recipient, db ):
        _save_one_ack( recipient, db )
        session = db()
        try:
            rows = NotificationRepository( session ).get_sender_conversation( _ACK_SENDER, recipient )
        finally:
            session.close()
        assert rows == [], f"an ack must not appear as a conversation message, got {len( rows )} row(s)"

    def test_an_ack_does_not_create_a_date_group_in_the_history_hydration( self, recipient, db ):
        """
        `get_sender_conversations_by_date` backs `/api/notifications/conversation-by-date`,
        which is what the multiplexer's history window hydrates from.
        """
        _save_one_ack( recipient, db )
        session = db()
        try:
            groups = NotificationRepository( session ).get_sender_conversations_by_date( _ACK_SENDER, recipient )
        finally:
            session.close()
        assert groups == [] or all( not g.get( "notifications" ) for g in groups ), (
            f"an ack must not create a date group, got {groups!r}" )

    def test_an_ack_does_not_create_a_date_summary( self, recipient, db ):
        _save_one_ack( recipient, db )
        session = db()
        try:
            summaries = NotificationRepository( session ).get_sender_date_summaries( _ACK_SENDER, recipient )
        finally:
            session.close()
        assert summaries == [], f"an ack must not create a date summary, got {summaries!r}"


class TestTheExclusionIsNARROWAndNotAGeneralBlackout:
    """
    🔴 FOUR EMPTY ANSWERS ABOVE ARE ALSO WHAT FOUR BROKEN QUERIES RETURN. These prove
    the queries still work — an ORDINARY notification from a different sender, saved
    alongside the ack, comes back from every one of them.
    """

    def _save_ordinary( self, session, recipient ):
        repo = NotificationRepository( session )
        repo.create_notification(
            sender_id="claude.code@lupin.deepily.ai#deadbeef", recipient_id=recipient,
            message="an ordinary message", type="task", priority="medium" )
        session.commit()
        return repo

    def test_an_ordinary_message_is_STILL_the_active_conversation( self, recipient, db ):
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = self._save_ordinary( session, recipient )
            assert repo.get_active_conversation( recipient ) == _REAL_SENDER
        finally:
            session.close()

    def test_an_ordinary_message_is_STILL_a_conversation_row( self, recipient, db ):
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = self._save_ordinary( session, recipient )
            rows = repo.get_sender_conversation( _REAL_SENDER, recipient )
            assert len( rows ) == 1 and rows[ 0 ].message == "an ordinary message"
        finally:
            session.close()

    def test_an_ordinary_message_STILL_produces_a_date_summary( self, recipient, db ):
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = self._save_ordinary( session, recipient )
            summaries = repo.get_sender_date_summaries( _REAL_SENDER, recipient )
            assert len( summaries ) == 1 and summaries[ 0 ][ "count" ] == 1
        finally:
            session.close()


class TestTheStructurALLYImmunePathsAreMeasuredNotAssumed:
    """
    🔴 "STRUCTURALLY IMMUNE" IS A CLAIM, AND AN UNMEASURED ONE IS A HOPE. Five paths
    carry NO ack exclusion because their own filters are supposed to keep acks out
    already. Mr. Radio asked for the evidence, and he was right to: an empty answer
    from a BROKEN query is indistinguishable from an empty answer from an immune one.

    So every case here has TWO arms. First the ack — the path must not see it. Then a
    row that SHOULD qualify — the path must see that. Only the pair distinguishes
    immunity from breakage, and only the pair would survive somebody deleting the
    filter that does the work.
    """

    def _repo( self, db ):
        return NotificationRepository( db() )

    def test_pending_ignores_the_ack_but_still_sees_a_real_pending_ask( self, recipient, db ):
        """Mechanism: response-pending states. An ack requests no response."""
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = NotificationRepository( session )
            assert repo.get_pending_for_recipient( recipient ) == [], "an ack is not a pending ask"

            row = repo.create_notification(
                sender_id=_REAL_SENDER, recipient_id=recipient, message="a real question?",
                type="task", priority="high", response_requested=True, response_type="yes_no" )
            session.commit()
            pending = repo.get_pending_for_recipient( recipient )
            assert len( pending ) == 1 and pending[ 0 ].id == row.id, (
                f"CONTROL FAILED — the pending query cannot see a genuine pending ask, "
                f"so its empty answer above proved nothing. Got {pending!r}" )
        finally:
            session.close()

    def test_undelivered_ignores_the_ack_but_still_sees_an_undelivered_row( self, recipient, db ):
        """
        Mechanism: state in (created, queued). An ack is marked delivered ON SAVE
        precisely so it never joins the AFK inbox and replays as a bodiless
        "missed notification".
        """
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = NotificationRepository( session )
            assert repo.get_undelivered_for_recipient( recipient ) == [], "an ack is never undelivered"
            assert repo.count_undelivered_for_recipient( recipient ) == 0

            repo.create_notification(
                sender_id=_REAL_SENDER, recipient_id=recipient,
                message="genuinely missed while away", type="task", priority="medium" )
            session.commit()
            missed = repo.get_undelivered_for_recipient( recipient )
            assert len( missed ) == 1, (
                f"CONTROL FAILED — the drain cannot see an ordinary undelivered row, so "
                f"its empty answer above proved nothing. Got {missed!r}" )
            assert repo.count_undelivered_for_recipient( recipient ) == 1, (
                "CONTROL FAILED — the COUNT disagrees with the getter it counts" )
        finally:
            session.close()

    def test_answers_owed_ignores_the_ack_but_still_sees_an_owed_answer( self, recipient, db ):
        """
        Mechanism: response_requested AND responded_at IS NOT NULL AND
        answer_delivered_at IS NULL. An ack satisfies none of the three.
        """
        from datetime import datetime, timezone
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = NotificationRepository( session )
            assert repo.get_answers_owed_for_persona( "Mr. Radio" ) == [], "an ack owes no answer"

            row = repo.create_notification(
                sender_id=_REAL_SENDER, recipient_id=recipient, message="answered question?",
                type="task", priority="high", response_requested=True,
                response_type="yes_no", sender_persona="Mr. Radio" )
            session.commit()
            row.responded_at = datetime.now( timezone.utc )
            session.commit()
            owed = repo.get_answers_owed_for_persona( "Mr. Radio" )
            assert len( owed ) == 1 and owed[ 0 ].id == row.id, (
                f"CONTROL FAILED — the owed query cannot see a genuinely owed answer, so "
                f"its empty answer above proved nothing. Got {owed!r}" )
        finally:
            session.close()

    def test_soft_delete_by_date_DOES_hide_the_ack( self, recipient, db ):
        """
        🔴 THE ONE THAT MUST GO THE OTHER WAY, AND IT IS THE REASON WRITE PATHS ARE
        CLASSIFIED SEPARATELY. If a delete could not SEE an ack, the user could never
        clear it: the row would sit in the table forever with no surface able to
        remove it. So this asserts the ack IS hidden — the opposite of every other
        assertion in this file, and deliberately so.
        """
        import datetime as _dt
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo   = NotificationRepository( session )
            today  = _dt.datetime.now( _dt.timezone.utc ).astimezone().strftime( "%Y-%m-%d" )
            hidden = repo.soft_delete_by_date( _ACK_SENDER, recipient, today )
            session.commit()
            assert hidden == 1, (
                f"a write path MUST be able to reach an ack, or the user can never clear "
                f"it — soft_delete_by_date hid {hidden} row(s), expected 1" )

            remaining = repo.get_latest_acks_for_broadcast( recipient, _BROADCAST_ID )
            assert remaining == [], "a soft-deleted ack must drop out of the per-broadcast read too"
        finally:
            session.close()


class TestTheAckIsStillReadableWhereItBelongs:

    def test_the_excluded_ack_STILL_comes_back_from_its_own_endpoint( self, recipient, db ):
        """
        🔴 A FIX THAT HID ACKS FROM THEIR OWN READ WOULD PASS EVERY OTHER ASSERTION IN
        THIS FILE. `get_latest_acks_for_broadcast` is the surface that exists to return
        them, and it must be untouched.
        """
        _save_one_ack( recipient, db )
        session = db()
        try:
            acks = NotificationRepository( session ).get_latest_acks_for_broadcast(
                recipient, _BROADCAST_ID )
        finally:
            session.close()
        assert len( acks ) == 1, f"the ack must still be readable by broadcast, got {acks!r}"
        assert acks[ 0 ].payload[ "session_id" ] == _SESSION_ID

    def test_the_ack_is_still_absent_from_both_rosters( self, recipient, db ):
        """b9136bcf's guarantee, re-asserted here so this branch cannot regress it."""
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = NotificationRepository( session )
            assert repo.get_sender_last_activities( recipient ) == []
            assert repo.get_sender_last_activities_visible( recipient ) == []
        finally:
            session.close()


class TestTheWINDOWQueryExcludesItToo:
    """
    🔴 MARÍA'S FINDING, AND SHE IS RIGHT: BOTH WINDOW READS CARRY *TWO* EXCLUSIONS, AND
    ONLY ONE OF THEM WAS WATCHED. `get_sender_conversation` and
    `get_sender_conversations_by_date` each filter twice — once in the ANCHOR lookup
    (`max(created_at)`, taken only when the caller passes no anchor) and once in the
    WINDOW query that actually returns the rows.

    Every earlier test here calls with anchor=None and a sender whose ONLY row is the
    ack, so the anchor lookup returns None and both methods bail out before the window
    query is ever built. The second clause could be deleted and nothing in this file
    would notice. MEASURED 2026-09-23: deleting the window clause in
    `get_sender_conversation` left 87 tests passing.

    The anchor is not a hypothetical parameter. `/api/notifications/conversation` and
    `/api/notifications/conversation-by-date` both expose `anchor` as a query param
    (routers/notifications.py), and the multiplexer sends one every time it pages back
    through history — so this is the path a user walks, not a contrived one.
    """

    def _anchor( self ):
        """Comfortably after the ack, so `created_at <= anchor` cannot fail on clock grain."""
        from datetime import datetime, timedelta, timezone
        return datetime.now( timezone.utc ) + timedelta( minutes=5 )

    def test_an_ack_is_not_a_conversation_row_when_the_caller_PASSES_AN_ANCHOR( self, recipient, db ):
        """Deleting the window clause at get_sender_conversation reddens exactly this."""
        _save_one_ack( recipient, db )
        session = db()
        try:
            rows = NotificationRepository( session ).get_sender_conversation(
                _ACK_SENDER, recipient, anchor=self._anchor() )
        finally:
            session.close()
        assert rows == [], (
            f"with an explicit anchor the anchor-lookup clause never runs, so the WINDOW "
            f"clause is the only thing excluding the ack — and it did not. Got {len( rows )} row(s)" )

    def test_an_ack_creates_no_date_group_when_the_caller_PASSES_AN_ANCHOR( self, recipient, db ):
        """Deleting the window clause at get_sender_conversations_by_date reddens exactly this."""
        _save_one_ack( recipient, db )
        session = db()
        try:
            groups = NotificationRepository( session ).get_sender_conversations_by_date(
                _ACK_SENDER, recipient, anchor=self._anchor() )
        finally:
            session.close()
        assert not groups, (
            f"with an explicit anchor the WINDOW clause is the only exclusion left, and "
            f"the ack came through it. Got {groups!r}" )

    def test_CONTROL_an_anchored_window_still_returns_an_ordinary_message( self, recipient, db ):
        """
        🔴 TWO EMPTY ANSWERS ABOVE ARE ALSO WHAT AN ANCHOR IN THE WRONG PLACE RETURNS.
        The same anchor, the same window, an ordinary row — it must come back, or the
        two assertions above are measuring a bad anchor rather than an exclusion.
        """
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = NotificationRepository( session )
            repo.create_notification(
                sender_id=_REAL_SENDER, recipient_id=recipient,
                message="an ordinary message", type="task", priority="medium" )
            session.commit()
            anchor = self._anchor()
            rows   = repo.get_sender_conversation( _REAL_SENDER, recipient, anchor=anchor )
            assert len( rows ) == 1, (
                f"CONTROL FAILED — this anchor/window returns nothing at all, so the two "
                f"empty answers above proved nothing. Got {rows!r}" )
            groups = repo.get_sender_conversations_by_date( _REAL_SENDER, recipient, anchor=anchor )
            assert groups, "CONTROL FAILED — the anchored date read is empty for a real message too"
        finally:
            session.close()


class TestTheTwoIMMUNEConstraintsThatNothingWasWatching:
    """
    🔴 MARÍA'S SECOND FINDING. Two STRUCTURALLY_IMMUNE reads name a constraint as their
    mechanism, and nothing here asked whether that constraint still exists. An immunity
    claim whose load-bearing filter can be deleted in silence is the same unmeasured
    hope the rest of this class was written to retire.
    """

    def test_dismiss_undelivered_leaves_the_ack_alone_but_still_dismisses_a_real_one( self, recipient, db ):
        """
        Mechanism: state in (created, queued). The ack is 'delivered', so the dismiss
        cannot reach it — and MUST not: `is_hidden=True` on an ack drops it out of
        `get_latest_acks_for_broadcast` (asserted in the soft-delete case above), so a
        dismiss that swept acks would silently erase the broadcast tally every time the
        user pressed "reset missed".
        """
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = NotificationRepository( session )
            assert repo.dismiss_undelivered_for_recipient( recipient ) == 0, (
                "the ack is 'delivered' and must be untouchable by the reset-missed dismiss" )
            session.commit()
            assert len( repo.get_latest_acks_for_broadcast( recipient, _BROADCAST_ID ) ) == 1, (
                "the ack must still be readable after a dismiss — a swept ack is a lost tally" )

            repo.create_notification(
                sender_id=_REAL_SENDER, recipient_id=recipient,
                message="genuinely missed while away", type="task", priority="medium" )
            session.commit()
            assert repo.dismiss_undelivered_for_recipient( recipient ) == 1, (
                "CONTROL FAILED — the dismiss cannot reach an ordinary undelivered row, "
                "so its zero above proved nothing" )
        finally:
            session.close()

    def test_the_dm_inbox_ignores_the_ack_but_still_sees_a_real_peer_dm( self, recipient, db ):
        """Mechanism: direction == 'ai_to_ai'. An ack is saved ai_to_human (the default)."""
        _save_one_ack( recipient, db )
        session = db()
        try:
            repo = NotificationRepository( session )
            assert repo.get_dm_inbox( recipient ) == [], "an ack is not a peer DM"

            row = repo.create_notification(
                sender_id=_REAL_SENDER, recipient_id=recipient, message="have you touched auth.py?",
                type="custom", priority="medium", direction="ai_to_ai" )
            session.commit()
            inbox = repo.get_dm_inbox( recipient )
            assert len( inbox ) == 1 and inbox[ 0 ].id == row.id, (
                f"CONTROL FAILED — the DM inbox cannot see a genuine peer DM, so its "
                f"empty answer above proved nothing. Got {inbox!r}" )
        finally:
            session.close()


class TestTheUndeliveredImmunityIsTheWATCHERSDoingNotTheQUERYS:
    """
    🔴 MARÍA'S THIRD FINDING, AND IT RELOCATES A MECHANISM. Three reads
    (`get_undelivered_for_recipient`, `count_undelivered_for_recipient`,
    `dismiss_undelivered_for_recipient`) are classified immune "because an ack is
    delivered". That is true — but NOTHING IN THOSE QUERIES MAKES IT TRUE. The ack is
    delivered because `CommonsAckWatcher._persist_ack_row` calls
    `repo.update_state( row.id, "delivered" )` on the line after it creates the row
    (`src/cosa/rest/commons_ack_watcher.py`, the `update_state` call inside `_persist_ack_row`).

    Delete that one line and all three immunity claims become false at once, in a file
    the classification guard never reads. This test is the pin: it asserts the SAVE
    STATE directly, so the mechanism has a watcher of its own rather than being an
    inference three classifications lean on.
    """

    def test_the_watcher_marks_the_ack_DELIVERED_on_save( self, recipient, db ):
        _save_one_ack( recipient, db )
        session = db()
        try:
            acks = NotificationRepository( session ).get_latest_acks_for_broadcast(
                recipient, _BROADCAST_ID )
            assert len( acks ) == 1, "the ack was not saved at all — this test measures nothing"
            assert acks[ 0 ].state == "delivered", (
                f"the ack was saved in state {acks[ 0 ].state!r}, not 'delivered'. Three "
                f"STRUCTURALLY_IMMUNE classifications rest on this line in "
                f"commons_ack_watcher._persist_ack_row; without it the ack joins the AFK drain "
                f"and replays as a bodiless 'missed notification'." )
        finally:
            session.close()
