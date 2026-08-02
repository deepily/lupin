"""
Integration test — late-answer handback pull inbox (§4.4 / §5), LIVE :8000 round-trip.

The one leg no unit tier can stand in for: the real answers-owed endpoint, the real
ack endpoint, and the real repo query, exercised over HTTP against the running server
and the migrated real DB (lupin_db_test carries migration 3da5c0d1eee6). The unit forms
(test_answers_owed_authlane_dv1.py, test_answers_owed_repo_realdb.py) drive throwaway
DBs in-process; this drives the server that ships.

What it proves, each anchored on a SEEDED row that MUST come back (an empty list is
NEVER the pass signal — this tier exists to catch a silent-empty):

  1. The owed row (answered, undelivered) is PRESENT — and THREE decoys sharing the
     same persona are EXCLUDED, one per owed-predicate term (§4.1/§4.4, C-V3/D-V3):
       - a forged default   (responded_at NULL)        → machine default, never served
       - an already-delivered row (answer_delivered_at set)
       - a stale row        (created_at 30d old)        → 24h age cap
     A unique per-run persona makes owed_count EXACT, so exclusion is proven by a
     falling count, not lost in a fleet backlog.
  2. Serving does NOT mark delivered (D-V2 half 1): after the GET, answer_delivered_at
     is still NULL in the table.
  3. Ack removes the row from owed but KEEPS it (ruling 2 + D-V2 half 2 + the redefined
     E-V4 steady state): POST /ack → the next GET no longer returns it, yet the row is
     still in the table with answer_delivered_at now set.

Venue: :8000 (mutates DB state; seeds/asserts via in-container get_db, drives HTTP via
requests). Submit via POST /api/test-suite/submit on a verified-idle server — never
side-doored. Self-cleaning in a finally block.

Design: src/rnd/v0.1.9/2026.08.01-late-answer-handback.md (§4.4, §5 integration tier).
"""

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests


# Per feedback_tests_parameterize_base_url — env var with sensible default.
BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )

_EMAIL    = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL" )
_PASSWORD = os.environ.get( "LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD" )

_ENDPOINT = f"{BASE_URL}/api/notifications/answers-owed"
_ACK      = f"{BASE_URL}/api/notifications/answers-owed/ack"


pytestmark = pytest.mark.skipif(
    not ( _EMAIL and _PASSWORD ),
    reason = "Requires LUPIN_TEST_INTERACTIVE_MOCK_JOBS_EMAIL + LUPIN_TEST_INTERACTIVE_MOCK_JOBS_PASSWORD env vars",
)


@pytest.fixture( scope="module" )
def auth_headers():
    """Login once per module → {"Authorization": "Bearer ..."}. The answers-owed lane
    is require_api_key_or_jwt; a Bearer JWT satisfies it."""
    resp = requests.post(
        f"{BASE_URL}/auth/login",
        json    = { "email": _EMAIL, "password": _PASSWORD },
        timeout = 10,
    )
    assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
    body   = resp.json()
    tokens = body.get( "tokens", body )
    token  = tokens.get( "access_token" ) or tokens.get( "accessToken" )
    assert token, f"No access_token in login response: {body}"
    return { "Authorization": f"Bearer {token}" }


def _ids_in( body ):
    """Set of notification ids in an answers-owed response (envelope uses 'id';
    tolerate 'notification_id' too)."""
    answers = body.get( "answers", [] ) if isinstance( body, dict ) else []
    out = set()
    for a in answers:
        for k in ( "id", "notification_id" ):
            if a.get( k ) is not None:
                out.add( str( a[ k ] ) )
    return out


def test_answers_owed_requires_auth():
    """The pull endpoint authenticates — an unauthenticated request is rejected, not a
    silent empty."""
    resp = requests.get( _ENDPOINT, params={ "persona": "nobody" }, timeout=10 )
    assert resp.status_code in ( 401, 403 ), resp.text


def test_owed_round_trip_serve_then_ack( auth_headers ):
    """
    The full pull-inbox contract on the live server + real DB.

    Seeds one genuinely-owed row plus three decoys (one per excluded predicate term)
    under a UNIQUE persona, then:
      - GET  → owed_count == 1, only the owed id present, all three decoys absent;
      - assert serving did NOT stamp answer_delivered_at (D-V2 half 1);
      - POST /ack the owed id;
      - GET  → owed_count == 0 (redefined E-V4 / D-V2 half 2: ack removes from owed);
      - assert the row is STILL in the table with answer_delivered_at now set (ruling 2).
    """
    from sqlalchemy import text
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import Notification

    persona   = f"itest-owed-{uuid.uuid4().hex[ :12 ]}"
    now       = datetime.now( timezone.utc )

    owed_id      = uuid.uuid4()
    forged_id    = uuid.uuid4()   # responded_at NULL  → machine default, excluded
    delivered_id = uuid.uuid4()   # answer_delivered_at set → already delivered, excluded
    stale_id     = uuid.uuid4()   # created_at 30d old → age-cap excluded
    all_ids      = [ owed_id, forged_id, delivered_id, stale_id ]

    def _notif( nid, **over ):
        base = dict(
            id                 = nid,
            sender_id          = "cc@lupin#itestsess",
            recipient_id       = None,          # set below to the real test user
            message            = f"owed-itest question {nid}",
            type               = "task",
            priority           = "high",
            created_at         = now,
            sender_persona     = persona,
            response_requested = True,
            responded_at       = now,
            answer_delivered_at= None,
            response_value     = { "value": "yes, proceed" },
            state              = "responded",
        )
        base.update( over )
        return Notification( **base )

    try:
        # ── seed (in-container get_db reaches lupin_db_test) ──
        with get_db() as session:
            row = session.execute(
                text( "SELECT id FROM users WHERE email = :e" ), { "e": _EMAIL }
            ).first()
            assert row is not None, f"test user {_EMAIL} not found"
            rid = row[ 0 ]

            session.add( _notif( owed_id,      recipient_id=rid ) )
            session.add( _notif( forged_id,    recipient_id=rid, responded_at=None,
                                 state="expired", response_value={ "value": "machine-default" } ) )
            session.add( _notif( delivered_id, recipient_id=rid, answer_delivered_at=now ) )
            session.add( _notif( stale_id,     recipient_id=rid,
                                 created_at=now - timedelta( days=30 ) ) )
            session.commit()

        # ── 1. pull: owed present, three decoys excluded, count EXACT ──
        resp = requests.get( _ENDPOINT, headers=auth_headers,
                             params={ "persona": persona, "limit": 100 }, timeout=15 )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body[ "status" ] == "success", body
        ids = _ids_in( body )
        assert str( owed_id ) in ids, f"seeded owed row MUST come back; got {ids} count={body.get('owed_count')}"
        assert str( forged_id )    not in ids, "forged default (responded_at NULL) must be excluded"
        assert str( delivered_id ) not in ids, "already-delivered row must be excluded"
        assert str( stale_id )     not in ids, "stale (30d) row must be excluded by the age cap"
        assert body[ "owed_count" ] == 1, f"exactly one owed row for this persona; got {body[ 'owed_count' ]}"

        # ── 2. serving did NOT stamp answer_delivered_at (D-V2 half 1) ──
        with get_db() as session:
            adr = session.execute(
                text( "SELECT answer_delivered_at FROM notifications WHERE id = :id" ),
                { "id": str( owed_id ) },
            ).scalar()
            assert adr is None, f"serving must NOT mark delivered; answer_delivered_at={adr!r}"

        # ── 3. ack, then re-pull: gone from owed, still in the table ──
        ack = requests.post( _ACK, headers=auth_headers,
                             json={ "notification_id": str( owed_id ) }, timeout=15 )
        assert ack.status_code == 200, ack.text

        resp2 = requests.get( _ENDPOINT, headers=auth_headers,
                              params={ "persona": persona, "limit": 100 }, timeout=15 )
        assert resp2.status_code == 200, resp2.text
        body2 = resp2.json()
        assert str( owed_id ) not in _ids_in( body2 ), "acked row must leave the owed set (redefined E-V4 / D-V2)"
        assert body2[ "owed_count" ] == 0, f"nothing owed after ack; got {body2[ 'owed_count' ]}"

        with get_db() as session:
            after = session.execute(
                text( "SELECT answer_delivered_at FROM notifications WHERE id = :id" ),
                { "id": str( owed_id ) },
            ).first()
            assert after is not None, "row must still exist after ack (ruling 2 — never delete)"
            assert after[ 0 ] is not None, "ack must stamp answer_delivered_at"

    finally:
        with get_db() as session:
            # id is a uuid column; bind strings and cast the column to text so psycopg2
            # does not try `uuid = text` (which has no operator).
            session.execute(
                text( "DELETE FROM notifications WHERE id::text = ANY(:ids)" ),
                { "ids": [ str( i ) for i in all_ids ] },
            )
            session.commit()


def test_dv4_cursor_orders_on_responded_at_not_created_at( auth_headers ):
    """
    D-V4 live (§4.4): the owed cursor advances on responded_at, NOT created_at.

    The subtlest bug in this area: a 20-hour-old ask answered two minutes ago must still
    be delivered — it sits inside the 24h age cap (keyed on created_at) yet its answer is
    fresh. Queried with a `since` responded_at cursor set 10 minutes ago:
      - LATE  (created 20h ago, responded 2 min ago) is AFTER the cursor → PRESENT. Its
        old created_at is the discriminator: were the cursor keyed on created_at, this row
        would sit behind a cursor that already passed its creation time and vanish — the
        exact silent miss D-V4 exists to catch.
      - DECOY (created 3h ago, responded 30 min ago) is BEFORE the cursor → ABSENT, so the
        `since` filter is proven non-vacuous, not a pass-through.
    With no cursor, both are within the age cap and owed (count 2) — an empty list is never
    the pass signal here.

    Venue: :8000 (mutates DB state). Self-cleaning.
    """
    from sqlalchemy import text
    from cosa.rest.db.database import get_db
    from cosa.rest.postgres_models import Notification

    persona = f"itest-dv4-{uuid.uuid4().hex[ :12 ]}"
    now     = datetime.now( timezone.utc )

    late_id  = uuid.uuid4()   # 20h-old ask, answered 2 min ago  → must return under the cursor
    decoy_id = uuid.uuid4()   # answered 30 min ago              → excluded by a 10-min cursor
    all_ids  = [ late_id, decoy_id ]

    def _notif( nid, created_at, responded_at, rid ):
        return Notification(
            id                 = nid,
            sender_id          = "cc@lupin#dv4sess",
            recipient_id       = rid,
            message            = f"dv4 question {nid}",
            type               = "task",
            priority           = "high",
            created_at         = created_at,
            sender_persona     = persona,
            response_requested = True,
            responded_at       = responded_at,
            answer_delivered_at= None,
            response_value     = { "value": "yes, proceed" },
            state              = "responded",
        )

    try:
        with get_db() as session:
            row = session.execute(
                text( "SELECT id FROM users WHERE email = :e" ), { "e": _EMAIL }
            ).first()
            assert row is not None, f"test user {_EMAIL} not found"
            rid = row[ 0 ]
            session.add( _notif( late_id,  now - timedelta( hours=20 ), now - timedelta( minutes=2 ),  rid ) )
            session.add( _notif( decoy_id, now - timedelta( hours=3 ),  now - timedelta( minutes=30 ), rid ) )
            session.commit()

        # ── no cursor: both owed, both inside the 24h age cap (age cap keys on created_at) ──
        resp = requests.get( _ENDPOINT, headers=auth_headers,
                             params={ "persona": persona, "limit": 100 }, timeout=15 )
        assert resp.status_code == 200, resp.text
        ids = _ids_in( resp.json() )
        assert str( late_id )  in ids, "20h-old-but-fresh-answer row must be owed (within age cap)"
        assert str( decoy_id ) in ids, "3h-old answered row must be owed"
        assert resp.json()[ "owed_count" ] == 2, resp.json()

        # ── since = 10 min ago (a responded_at cursor): LATE returns, DECOY excluded ──
        since = ( now - timedelta( minutes=10 ) ).isoformat()
        resp2 = requests.get( _ENDPOINT, headers=auth_headers,
                              params={ "persona": persona, "since": since, "limit": 100 }, timeout=15 )
        assert resp2.status_code == 200, resp2.text
        ids2 = _ids_in( resp2.json() )
        assert str( late_id ) in ids2, (
            "LATE (created 20h ago, responded 2 min ago) MUST return under a 10-min responded_at "
            "cursor — its presence proves the cursor keys on responded_at, not created_at"
        )
        assert str( decoy_id ) not in ids2, (
            "DECOY (responded 30 min ago) must be excluded by the 10-min cursor — proves `since` "
            "filters on responded_at and is not a no-op"
        )
        assert resp2.json()[ "owed_count" ] == 1, resp2.json()

    finally:
        with get_db() as session:
            session.execute(
                text( "DELETE FROM notifications WHERE id::text = ANY(:ids)" ),
                { "ids": [ str( i ) for i in all_ids ] },
            )
            session.commit()
