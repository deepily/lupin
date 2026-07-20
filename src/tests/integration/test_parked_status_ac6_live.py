"""
AC6 — the LIVE proof that park → expire → rejoin actually works.

Seat 3 (Rachel 🕊️). Design: src/rnd/v0.1.9/2026.07.19-parked-status-board-hygiene.md
Derivation + triage: src/rnd/v0.1.9/2026.07.19-parked-status-marker-predicate-and-triage.md
Store rows: 954428b3 (design) · 6b61a22c (this seat) · d291028e (readers)

VENUE: :8000 monopolize-mode, SCHEDULED ONLY — submit via POST /api/test-suite/submit,
NEVER a side door. Creates and transitions real task_items rows ⇒ NOT :7999-eligible.

═══ WHY THIS FILE EXISTS AND THE UNIT SUITE IS NOT ENOUGH ═══

`src/tests/unit/test_task_store_parked_parity.py` (33 passed) proves the owed
PREDICATE: that the SQLAlchemy twin and the row twin agree, on every status ×
every chase shape, with every single-expression mutation caught. It proves the
READ side completely.

It CANNOT prove AC6, for two reasons it states about itself:

  1. It constructs rows DIRECTLY in in-memory SQLite. It never transitions a row
     through the API, so it says nothing about whether a row can ever REACH
     `parked`. On 2026-07-19 the answer was NO — `park_reason` existed as a
     column and as a rules parameter, and nothing carried it from a caller to a
     row: absent from `TaskTransitionIn`, absent from the handler call site,
     absent from the repository, absent from the MCP transport. The unit suite
     was green at 9823, all four readers were wired, three seats reported done,
     and the feature was unreachable through its own front door. EVERY
     INSTRUMENT WE HAD SAID YES; THE ONE THAT WOULD HAVE SAID NO IS THE ONE
     NOBODY HAD RUN. That is the whole argument for a live gate over a formality.

  2. SQLite has no `timestamptz`. The unit suite stores naive-UTC on both sides so
     its comparison is well-defined — which means the tz-aware Postgres boundary,
     precisely where a naive/aware mix would shift the result, is explicitly OUT
     of its scope. Only this file runs against real `timestamptz` columns.

⇒ A green unit suite is NOT authority to park anything. This file is.

═══ THE ONE ASSERTION THAT IS ACTUALLY AC6 ═══

`test_park_expires_by_the_passage_of_time_alone` parks a row with a chase a few
seconds out, confirms it is silent, WAITS for real wall-clock time to pass, and
confirms it has rejoined the owed count — WITHOUT ANY WRITE IN BETWEEN. No
transition, no daemon, no sweeper, no human. That is the design's central claim
("expiry is computed at READ time and never written back") and it is the only
test here that can falsify it.

Every other test in this file is a supporting control.
"""

import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
import requests

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories import ApiKeyRepository, UserRepository
from lupin_cli.claude_code.hooks.lib.task_store_client import query_owed

BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
ENDPOINT = f"{BASE_URL}/api/tasks"

# The chase offset used by the passage-of-time test. Long enough that the park is
# genuinely in force when first read, short enough not to pad the suite.
EXPIRY_WINDOW_SECONDS = 4


@pytest.fixture
def test_api_key( clean_test_db ):
    """Create a test API key and store its bcrypt hash in the test database."""
    api_key   = "ck_live_" + secrets.token_urlsafe( 48 )
    key_bytes = api_key.encode( "utf-8" )
    salt      = bcrypt.gensalt( rounds=12 )
    key_hash  = bcrypt.hashpw( key_bytes, salt ).decode( "utf-8" )

    email = f"test-park-{uuid.uuid4()}@test.com"

    with get_db() as session:
        user = UserRepository( session ).create_user(
            email         = email,
            password_hash = "dummy_hash",
            roles         = [ "service_account" ],
        )
        user.email_verified = True
        user.is_active      = True

        ApiKeyRepository( session ).create_key(
            user_id     = user.id,
            key_hash    = key_hash,
            description = "AC6 parked-status integration test key",
        )
        session.commit()
        return { "api_key": api_key, "user_id": user.id, "email": email }


@pytest.fixture
def persona( ):
    """
    A persona name unique to this test.

    ISOLATION IS LOAD-BEARING: every assertion below is an EXACT owed COUNT, and
    an exact count is only meaningful if no other row on the board shares the
    filter. A shared persona would make every count a moving target and the
    suite would go flaky in a way that reads as a park defect.
    """
    return f"ac6-{uuid.uuid4().hex[ :12 ]}"


@pytest.fixture
def store_settings( ):
    """
    A LOCAL settings dict pinned to BASE_URL (:8000).

    ⚠️ DO NOT REPLACE THIS WITH `load_task_store_settings()`. It looks like the
    "real" thing to use and it would silently break this suite: the real loader
    resolves `api_base_url` from the hook config block, which points at **:7999**.
    Rows would be CREATED on :8000 and the owed count READ from :7999 — two
    different databases. The suite would then report a confident number about a
    server that never saw the row, and could false-PASS (dev happens to hold a
    matching count) or false-FAIL. Either way the failure presents as a PARK bug
    rather than a VENUE bug, which routes the diagnosis to the wrong layer.

    Caught in review by Krishna 🦚, who owns the loader. Recording the REASONING
    rather than only the conclusion: this fixture was originally written as a
    local dict for convenience, NOT because the hazard had been considered. It was
    correct-by-accident, now made correct-on-purpose — the next reader who reaches
    for the real loader should hit the reason before making the change.
    """
    return { "api_base_url": BASE_URL, "timeout_seconds": 10.0 }


@pytest.fixture( scope="module", autouse=True )
def require_parked_schema( ):
    """
    🔴 PREFLIGHT — fail with a VENUE diagnosis before any park test runs.

    On 2026-07-19 `lupin_db_test` sat at stamp `f2a3b4c5d6e7` with NO `park%`
    columns, while `lupin_db_dev` was at `c1a7f0e2b9d4` with `park_reason`
    present. **The test database had never been stamped with the parked
    migration.** Without this fixture every test below would have gone red on
    missing schema, and a red in a file called "parked status AC6" reads as a
    PARK DEFECT — a misdiagnosis that routes work to the wrong layer.

    Caught by Mr. Radio 🦉 querying both databases directly before submitting.
    Encoded here so the check is mechanical rather than remembered: it belonged
    to nobody's plan and would not have survived as a habit.

    The failure message names the remedy, because a preflight that only says
    "column missing" still costs the reader the diagnosis.
    """
    from sqlalchemy import inspect as sa_inspect, text

    with get_db() as session:
        columns = { c[ "name" ] for c in sa_inspect( session.bind ).get_columns( "task_items" ) }
        stamp   = session.execute( text( "SELECT version_num FROM alembic_version" ) ).scalar()

    missing = { "park_reason" } - columns
    if missing:
        pytest.fail(
            f"VENUE FAULT, NOT A PARK DEFECT — the database behind {BASE_URL} is missing "
            f"{sorted( missing )} on task_items (alembic stamp: {stamp!r}).\n"
            f"The parked migration (c1a7f0e2b9d4) has not been applied to this database.\n"
            f"REMEDY: bounce the test container so alembic upgrades to head, confirm "
            f"task_items.park_reason exists, then re-submit. Do NOT read the failures "
            f"below as evidence about the park predicate — they would be evidence about "
            f"the schema.",
            pytrace=False,
        )


def _headers( api_key ):
    return { "X-API-Key": api_key }


def _create_row( api_key, persona, title="AC6 park subject" ):
    """Create a queued row owned by `persona`. Returns the row dict."""
    body = {
        "item_class"          : "task",
        "title"               : title,
        "project"             : "lupin",
        "owner_persona"       : persona,
        "accountable_manager" : persona,
        "created_by"          : "rachel ac6",
        "priority"            : "P3",
    }
    r = requests.post( ENDPOINT, json=body, headers=_headers( api_key ), timeout=15 )
    assert r.status_code == 201, f"create failed {r.status_code}: {r.text}"
    row = r.json()
    assert row[ "status" ] == "queued"
    return row


def _park( api_key, task_id, chase_ts, park_reason, expect=200 ):
    """
    Transition a row to `parked` through the REAL API.

    ⚠️ This is the call that was IMPOSSIBLE on 2026-07-19 — `park_reason` had no
    path from a caller to the row. If this file ever starts failing here with a
    422 naming park_reason, the wiring has regressed, not the predicate.
    """
    payload = {
        "to_status"     : "parked",
        "actor"         : "rachel ac6",
        "authority"     : "standing",
        "next_chase_ts" : chase_ts.isoformat(),
        "park_reason"   : park_reason,
    }
    r = requests.post( f"{ENDPOINT}/{task_id}/transition", json=payload,
                       headers=_headers( api_key ), timeout=15 )
    assert r.status_code == expect, f"park expected {expect}, got {r.status_code}: {r.text}"
    return r


def _owed_count( store_settings, api_key, persona ):
    """
    R2's REAL owed-count path — the one the Stop hook fires on.

    NOT the predicate, NOT query_tasks. `query_owed` issues the single
    `owed_only=true&count_only=true` request the hook makes. Asserting on the
    predicate instead would pass cleanly while the hook stayed permanently
    silent, because both twins would agree the row is owed and the hook simply
    would never ask.
    """
    ok, count = query_owed( store_settings, api_key, persona, project="lupin" )
    assert ok, "R2 owed-count read failed — fail-safe returned not-ok"
    return count


def _get_row( api_key, task_id ):
    r = requests.get( f"{ENDPOINT}/{task_id}", headers=_headers( api_key ), timeout=15 )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    return r.json()


# ===========================================================================
# AC6 — the load-bearing test
# ===========================================================================

class TestAC6ParkExpireRejoin:

    def test_park_expires_by_the_passage_of_time_alone( self, test_api_key, persona, store_settings ):
        """
        🔴 THIS IS AC6. Everything else in this file supports it.

        Park a row with a chase a few seconds out; confirm it goes silent;
        WAIT for real time to pass; confirm it has rejoined the owed count —
        with NO write, NO transition, NO daemon in between.

        If self-expiry were implemented as a written-back flag or a sweeper, this
        test fails: nothing runs during the sleep.
        """
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )

        baseline = _owed_count( store_settings, api_key, persona )
        assert baseline == 1, f"fixture not isolated — expected exactly 1 owed row, got {baseline}"

        chase = datetime.now( timezone.utc ) + timedelta( seconds=EXPIRY_WINDOW_SECONDS )
        _park( api_key, row[ "id" ], chase, "AC6: bounded silence, self-expiring" )

        during = _owed_count( store_settings, api_key, persona )
        assert during == 0, f"park bought NO silence — owed count still {during}"

        # No write happens here. Only time passes.
        time.sleep( EXPIRY_WINDOW_SECONDS + 2 )

        after = _owed_count( store_settings, api_key, persona )
        assert after == 1, (
            f"THE ROW DID NOT REJOIN. owed count {after}, expected 1. Park bought "
            f"PERMANENT silence — the central claim of the design is false."
        )

        # And it rejoined WITHOUT its status being rewritten: expiry is computed
        # at read time. A written-back unpark would show status='queued' here.
        still = _get_row( api_key, row[ "id" ] )
        assert still[ "status" ] == "parked", (
            "status was written back to un-park — expiry must be computed at READ "
            "time, never persisted (a sweeper that stops running leaves rows "
            "parked forever, silently)"
        )

    def test_expired_park_is_counted_exactly_once( self, test_api_key, persona, store_settings ):
        """
        THE DOUBLE-COUNT GUARD, live.

        The retired shape looped the status tuple and SUMMED per-status counts,
        which would admit an expired-parked row on the `queued` pass AND the
        `in_progress` pass — counting it twice, so a parked board would read as
        busier than an unparked one.

        Asserted as an EXACT total, never a delta and never "> 0": a delta
        assertion passes at 2 when the baseline was also doubled.
        """
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )

        past = datetime.now( timezone.utc ) - timedelta( hours=6 )
        _park( api_key, row[ "id" ], past, "AC6: already-expired park" )

        count = _owed_count( store_settings, api_key, persona )
        assert count == 1, f"expired parked row counted {count} times, expected exactly 1"

    def test_active_park_is_silent_and_expired_park_is_not( self, test_api_key, persona, store_settings ):
        """
        THE DISCRIMINATING CONTROL — two rows, same persona, opposite chases.

        Without this, the AC6 test passes for the wrong reason: a reader that
        counts EVERYTHING also counts the expired row. One row must be counted
        and the other must not, on the same query.
        """
        api_key = test_api_key[ "api_key" ]
        future_row = _create_row( api_key, persona, title="AC6 still-parked" )
        past_row   = _create_row( api_key, persona, title="AC6 expired" )

        now = datetime.now( timezone.utc )
        _park( api_key, future_row[ "id" ], now + timedelta( days=1 ), "AC6: chase still ahead" )
        _park( api_key, past_row[ "id" ],   now - timedelta( days=1 ), "AC6: chase has passed" )

        count = _owed_count( store_settings, api_key, persona )
        assert count == 1, (
            f"owed count {count}, expected exactly 1 — the reader cannot "
            f"distinguish an ACTIVE park from an EXPIRED one"
        )


# ===========================================================================
# The write path — the half the unit suite structurally cannot reach
# ===========================================================================

class TestParkWritePath:

    def test_park_reason_is_persisted_on_the_row( self, test_api_key, persona ):
        """
        `park_reason` must survive the round trip.

        ⚠️ THIS IS THE REGRESSION GUARD FOR THE 2026-07-19 GAP. The column, both
        CHECK constraints and `validate_park` all existed while NOTHING carried
        the value from a caller to the row. A test that only asserted "park
        returns 200" would not have caught it.
        """
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )
        reason  = "TABLED, NOT CLOSED — everything else can wait"

        _park( api_key, row[ "id" ], datetime.now( timezone.utc ) + timedelta( days=1 ), reason )

        stored = _get_row( api_key, row[ "id" ] )
        assert stored[ "status" ] == "parked"
        assert stored.get( "park_reason" ) == reason, (
            f"park_reason did not survive the write path: {stored.get( 'park_reason' )!r}"
        )

    def test_park_write_advances_updated_ts_using_server_values_only( self, test_api_key, persona ):
        """
        The row is born NOT-STALE: the park write advances `updated_ts`.

        ⚠️ THE LOAD-BEARING HALF IS WHAT THIS TEST REFUSES TO TOUCH — the test's
        own `now()`. Both timestamps below come from the SERVER: `before` from the
        create response, `after` from the transition response. Comparing a server
        timestamp against a locally-generated `datetime.now()` measures the gap
        between two clocks, not the behaviour of the write — and it would pass or
        fail on machine drift, which is the flakiest possible reason for a gate to
        move.

        SCOPE, stated so nobody reads more into it than it proves: this asserts
        only that the park write refreshed `updated_ts`. The AC3 equality
        assertion — `park_reason_captured_at == updated_ts` — belongs to the
        STALENESS build, whose column does not exist yet and correctly is not in
        migration `c1a7f0e2b9d4`. It gets written in that build's own tests, not
        smuggled into this gate, which ships first.
        """
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )

        before = datetime.fromisoformat( row[ "updated_ts" ] )

        resp  = _park( api_key, row[ "id" ],
                       datetime.now( timezone.utc ) + timedelta( days=1 ),
                       "AC6: row must be born not-stale" )
        after = datetime.fromisoformat( resp.json()[ "item" ][ "updated_ts" ] )

        assert after > before, (
            f"park did not advance updated_ts ({before.isoformat()} -> {after.isoformat()}) "
            f"— the row is born STALE, and any staleness reader would treat a "
            f"freshly-parked row as neglected"
        )

    def test_park_without_reason_is_rejected( self, test_api_key, persona ):
        """park_reason is REQUIRED — a park nobody can refute is not a park."""
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )

        r = requests.post(
            f"{ENDPOINT}/{row[ 'id' ]}/transition",
            json={
                "to_status"     : "parked",
                "actor"         : "rachel ac6",
                "next_chase_ts" : ( datetime.now( timezone.utc ) + timedelta( days=1 ) ).isoformat(),
            },
            headers=_headers( api_key ), timeout=15,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
        assert "park_reason" in r.text

    def test_park_without_chase_is_rejected( self, test_api_key, persona ):
        """
        next_chase_ts is REQUIRED — the chase IS the un-park.

        An indefinite hold is `dropped` with a reason, because dropping is
        VISIBLE. A park with no chase would be an invisible exit.
        """
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )

        r = requests.post(
            f"{ENDPOINT}/{row[ 'id' ]}/transition",
            json={ "to_status": "parked", "actor": "rachel ac6", "park_reason": "no chase supplied" },
            headers=_headers( api_key ), timeout=15,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"
        assert "next_chase_ts" in r.text

    def test_park_from_blocked_is_rejected( self, test_api_key, persona ):
        """
        Park is legal ONLY from queued / in_progress.

        This is what makes re-admitting the expired-parked set an exact
        RESTORATION rather than a widening: every expired-parked row provably
        came from the statuses R2 already counted. If a blocked row could park,
        expiring it would inject a row R2 never counted before.
        """
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )

        blocked = requests.post(
            f"{ENDPOINT}/{row[ 'id' ]}/transition",
            json={
                "to_status"     : "blocked",
                "actor"         : "rachel ac6",
                "blocked_by"    : [ { "kind": "user", "id": "rick" } ],
                "next_chase_ts" : ( datetime.now( timezone.utc ) + timedelta( days=1 ) ).isoformat(),
            },
            headers=_headers( api_key ), timeout=15,
        )
        assert blocked.status_code == 200, f"setup blocked-transition failed: {blocked.text}"

        r = requests.post(
            f"{ENDPOINT}/{row[ 'id' ]}/transition",
            json={
                "to_status"     : "parked",
                "actor"         : "rachel ac6",
                "next_chase_ts" : ( datetime.now( timezone.utc ) + timedelta( days=1 ) ).isoformat(),
                "park_reason"   : "should not be permitted from blocked",
            },
            headers=_headers( api_key ), timeout=15,
        )
        assert r.status_code == 422, f"expected 422, got {r.status_code}: {r.text}"


# ===========================================================================
# Board visibility — hidden by default, surfaced on request
# ===========================================================================

class TestParkedVisibility:

    def test_park_active_row_is_hidden_by_default_and_surfaced_explicitly( self, test_api_key, persona ):
        """A parked row is suppressed from the default board and reachable via the audit surface."""
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )
        _park( api_key, row[ "id" ], datetime.now( timezone.utc ) + timedelta( days=1 ), "AC6: hidden by default" )

        default = requests.get( ENDPOINT, params={ "owner_persona": persona },
                                headers=_headers( api_key ), timeout=15 ).json()
        assert row[ "id" ] not in [ t[ "id" ] for t in default[ "tasks" ] ], (
            "a park-ACTIVE row is visible on the default board — parking bought no quiet"
        )

        audit = requests.get( ENDPOINT, params={ "owner_persona": persona, "status": "parked" },
                              headers=_headers( api_key ), timeout=15 ).json()
        assert row[ "id" ] in [ t[ "id" ] for t in audit[ "tasks" ] ], (
            "an explicit status=parked query did not surface the row — parked rows "
            "would be unauditable, which is an exit, not a hold"
        )

    def test_expired_park_is_visible_on_the_default_board( self, test_api_key, persona ):
        """
        An EXPIRED park must be visible again, not merely counted.

        A row that pokes you while staying invisible on the board is the exact
        incoherence this build exists to remove.
        """
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )
        _park( api_key, row[ "id" ], datetime.now( timezone.utc ) - timedelta( days=1 ), "AC6: expired, must resurface" )

        default = requests.get( ENDPOINT, params={ "owner_persona": persona },
                                headers=_headers( api_key ), timeout=15 ).json()
        assert row[ "id" ] in [ t[ "id" ] for t in default[ "tasks" ] ], (
            "an EXPIRED parked row is invisible on the board while counting as owed"
        )


# ===========================================================================
# tz-aware Postgres — the boundary the unit suite explicitly carves out
# ===========================================================================

class TestTimezoneAwareBoundary:

    def test_chase_stored_and_compared_as_tz_aware( self, test_api_key, persona, store_settings ):
        """
        The gap the unit suite names and cannot close.

        SQLite has no `timestamptz`, so the unit gate stores naive-UTC on both
        sides. Here the column is a real `timestamptz`. A park expressed in a
        NON-UTC offset must behave identically to the same instant in UTC — if
        the comparison silently dropped tz, an offset chase would shift by hours
        and this is the only place that would show it.
        """
        api_key = test_api_key[ "api_key" ]
        row     = _create_row( api_key, persona )

        # 5 hours ago expressed as a -04:00 offset — the same INSTANT as UTC-5h,
        # but a naive read would misinterpret the wall-clock digits.
        past_edt = datetime.now( timezone( timedelta( hours=-4 ) ) ) - timedelta( hours=5 )
        _park( api_key, row[ "id" ], past_edt, "AC6: tz-aware, expressed in EDT" )

        count = _owed_count( store_settings, api_key, persona )
        assert count == 1, (
            f"a chase 5h in the past expressed as -04:00 did not expire (owed={count}) "
            f"— the comparison is dropping timezone information"
        )

        stored = _get_row( api_key, row[ "id" ] )
        assert stored[ "next_chase_ts" ] is not None
        assert stored[ "status" ] == "parked"
