"""
AC3 — the LIVE proof that park captures the POST-write `updated_ts`.

Seat 3 (session 092d7ae6). Design: src/rnd/v0.1.9/2026.07.19-park-reason-staleness-detection.md
Store row: 4ce27ba1. Companion unit suite: src/tests/unit/test_park_reason_staleness.py

VENUE: :8000 monopolize-mode, SCHEDULED ONLY — submit via POST /api/test-suite/submit,
NEVER a side door. Creates, parks and amends real task_items rows ⇒ NOT :7999-eligible.
Rides in ONE submission with seat 2's AC10 (manager ruling 2026-07-19): both claims are
"the real write path on real Postgres", the same fixture surface, one monopolize window.

═══ WHY AC3 CANNOT LIVE IN THE UNIT SUITE ═══

Equality on a row the real write path parked is a claim about the WRITE; the
weaker `stale == False` is what §3.4 calls one assertion short; and since PG's
transaction-stable `now()` gives equality under all three orderings, this
assertion is what makes seat 2's explicit pin observable.

Unpacking each clause, because each is load-bearing:

  1. A CLAIM ABOUT THE WRITE. The unit suite constructs rows in SQLite and never
     transitions one through the API, so it can prove the PREDICATE's arithmetic
     and nothing about what the writer stamps. AC3 is `park_reason_captured_at
     == updated_ts` on a row the writer actually parked.

  2. ONE ASSERTION SHORT. Asserting merely `stale == False` after a park also
     passes for a `now()`-written-after implementation, which leaves an
     undetectable amendment window between the `updated_ts` stamp and the
     capture. Pin the mechanism (equality), do not sample a consequence.

  3. AND THE REASON A PG GREEN IS NOT SELF-SUFFICIENT: Postgres `now()` is
     `transaction_timestamp()` and is STABLE across a transaction, so all three
     candidate write orderings — pre-write, post-write, and `now()` — produce
     exact equality at park. §3.4's born-stale arm CANNOT FIRE within one
     transaction on PG. That is luck, not design. A passing equality here does
     not by itself prove the ordering was implemented correctly; it proves the
     row is INTERNALLY CONSISTENT. (Finding: seat 2, session 7889d857.)

⚠️ THE ORDERING THIS FILE ORIGINALLY REASONED ABOUT NO LONGER EXISTS — updated
2026-07-19 19:08, and the correction is left visible rather than overwritten
because THIS DOCSTRING WENT STALE THE EXACT WAY `park_reason` DOES: still
syntactically valid, still plausible, describing a mechanism the code had
stopped having. In the build written to detect that. It is worth one paragraph.

WHAT CHANGED: §3.4 prescribed capturing the POST-write `updated_ts` — a
two-step. Seat 2 found §3.1's CHECK (`status != 'parked' OR
park_reason_captured_at IS NOT NULL`) FORBIDS that sequence outright, and PG
cannot defer a CHECK, so the two-step cannot commit in EITHER order. The landed
implementation is ONE DB-clock read assigned to BOTH columns in a SINGLE
statement, with `updated_ts` written explicitly to suppress its `onupdate`.

WHAT THAT DOES TO AC3, stated precisely because "unaffected" is too coarse: the
assertions below do not change, but WHAT THEY PROVE does. Under a single
statement, equality at park is true BY CONSTRUCTION — one value, two columns. So
AC3 has shifted from DETECTING an ordering error to PINNING THE CONSTRUCTION
against a future regression: it goes red the day someone reintroduces a two-step,
a second clock read, or a `now()` default. That is a regression guard, not a
discovery instrument, and it should not be cited as the latter.

⇒ WHICH WAY THIS SUITE LIES, stated per §6 rule 10: it lies toward PASS on the
  ordering question. It CANNOT be sole authority that the writer is correct —
  under the single-statement write it very nearly cannot fail on a fresh park,
  which is precisely why `test_the_equality_assertion_is_not_vacuous` exists and
  why it is the load-bearing control rather than a courtesy. It IS authority
  that the two columns can diverge, that the capture is FROZEN at park, and that
  amendments are detected. Those three are what the feature actually rests on.

═══ WHAT THIS SUITE COVERS, AND WHAT IT DOES NOT ═══

COVERS  : the real write path on real Postgres with real timestamptz columns —
          park stamps both columns; an amendment through PATCH makes the row
          stale; staleness is advisory on the live owed count.
SILENT ON: the predicate's boundary matrix (unit suite owns it, 29 tests, 8
          mutants) and whether a row can reach `parked` at all (AC6-live owns
          it, run ts-0e8c0fb2).

No control here re-licenses those; see §6 rule 14.
"""

import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pytest
import requests

from cosa.rest.db.database import get_db
from cosa.rest.db.repositories.api_key_repository import ApiKeyRepository
from cosa.rest.db.repositories.user_repository import UserRepository
from lupin_cli.claude_code.hooks.lib.task_store_client import query_owed

BASE_URL = os.environ.get( "LUPIN_TEST_BASE_URL", "http://localhost:8000" )
ENDPOINT = f"{BASE_URL}/api/tasks"

# Far enough out that the park is unambiguously ACTIVE for every read in this
# file. Nothing here tests expiry — that is AC6-live's job, and a short window
# would silently turn these into expiry tests.
CHASE_HOURS = 6


@pytest.fixture
def test_api_key( clean_test_db ):
    """Create a test API key and store its bcrypt hash in the test database."""
    api_key   = "ck_live_" + secrets.token_urlsafe( 48 )
    key_bytes = api_key.encode( "utf-8" )
    salt      = bcrypt.gensalt( rounds=12 )
    key_hash  = bcrypt.hashpw( key_bytes, salt ).decode( "utf-8" )

    email = f"test-stale-{uuid.uuid4()}@test.com"

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
            description = "AC3 park_reason-staleness integration test key",
        )
        session.commit()
        return { "api_key": api_key, "user_id": user.id, "email": email }


@pytest.fixture
def persona( ):
    """
    A persona name unique to this test.

    ISOLATION IS LOAD-BEARING for the AC7 owed-count assertions: an exact count
    is only meaningful if no other row on the board shares the filter.
    """
    return f"ac3-{uuid.uuid4().hex[ :12 ]}"


@pytest.fixture
def store_settings( ):
    """
    A LOCAL settings dict pinned to BASE_URL (:8000).

    ⚠️ DO NOT REPLACE WITH `load_task_store_settings()` — it resolves
    `api_base_url` from the hook config block, which points at :7999. Rows would
    be created on :8000 and counts read from :7999: two different databases, and
    the resulting failure presents as a STALENESS bug rather than a VENUE bug.
    Inherited verbatim from AC6-live, where Krishna 🦚 caught it.
    """
    return { "api_base_url": BASE_URL, "timeout_seconds": 10.0 }


@pytest.fixture( scope="module", autouse=True )
def require_staleness_schema( ):
    """
    🔴 PREFLIGHT — fail with a VENUE diagnosis before any staleness test runs.

    Directly earned on 2026-07-19: seat 1 added `park_reason_captured_at` to
    `postgres_models.py` while migration `d47487369407` was still unwritten, and
    because :7999 runs uvicorn `--reload` the model edit hot-loaded into the live
    server — every `task_query` 500'd with `UndefinedColumn`. On a --reload
    server THE MODEL EDIT IS THE DEPLOY.

    Without this fixture, that same drift on :8000 would redden every test below
    and a red in a file named "staleness" reads as a STALENESS defect. It is a
    schema fault. The message names the remedy, because a preflight that only
    says "column missing" still costs the reader the diagnosis.
    """
    from sqlalchemy import inspect as sa_inspect, text

    with get_db() as session:
        columns = { c[ "name" ] for c in sa_inspect( session.bind ).get_columns( "task_items" ) }
        stamp   = session.execute( text( "SELECT version_num FROM alembic_version" ) ).scalar()

    missing = { "park_reason", "park_reason_captured_at" } - columns
    if missing:
        pytest.fail(
            f"VENUE FAULT, NOT A STALENESS DEFECT — the database behind {BASE_URL} is "
            f"missing {sorted( missing )} on task_items (alembic stamp: {stamp!r}).\n"
            f"REMEDY: confirm the staleness migration has been written AND applied, "
            f"bounce the test container so alembic upgrades to head, then re-submit. "
            f"Do NOT read the failures below as evidence about the staleness "
            f"predicate — they would be evidence about the schema.",
            pytrace=False,
        )


def _headers( api_key ):
    return { "X-API-Key": api_key }


def _create_row( api_key, persona, title="AC3 staleness subject" ):
    """Create a queued row owned by `persona`. Returns the row dict."""
    body = {
        "item_class"          : "task",
        "title"               : title,
        "project"             : "lupin",
        "owner_persona"       : persona,
        "accountable_manager" : persona,
        "created_by"          : "seat3 ac3",
        "priority"            : "P3",
    }
    r = requests.post( ENDPOINT, json=body, headers=_headers( api_key ), timeout=15 )
    assert r.status_code == 201, f"create failed {r.status_code}: {r.text}"
    return r.json()


def _park( api_key, task_id, park_reason, chase_hours=CHASE_HOURS ):
    """Transition a row to `parked` through the REAL API."""
    chase = datetime.now( timezone.utc ) + timedelta( hours=chase_hours )
    payload = {
        "to_status"     : "parked",
        "actor"         : "seat3 ac3",
        "authority"     : "standing",
        "next_chase_ts" : chase.isoformat(),
        "park_reason"   : park_reason,
    }
    r = requests.post( f"{ENDPOINT}/{task_id}/transition", json=payload,
                       headers=_headers( api_key ), timeout=15 )
    assert r.status_code == 200, f"park failed {r.status_code}: {r.text}"
    return r.json()


def _amend( api_key, task_id, **fields ):
    """
    Amend a PARKED row's mutable fields through the real PATCH endpoint.

    ⚠️ THIS IS THE DEFECT SCENARIO ITSELF, not a synthetic stand-in. PATCH is
    whitelisted to title/body/priority/owner/manager/gate_class and can NEVER
    touch status or park_reason — so the row STAYS parked, its frozen quote is
    left syntactically intact, and the thing the quote described has changed
    underneath it. That is precisely "the quote stops being true and NOTHING GOES
    RED" (§1). `body_changed_ts` bumps; `park_reason_captured_at` does not.

    ⚠️ SINCE BUG 54924128 (2026-07-26) THE FIELD YOU PASS DECIDES THE OUTCOME.
    Staleness reads `body_changed_ts`, which only a real BODY change moves. So
    `_amend( ..., body=... )` makes a parked row stale and `_amend( ..., title=... )`
    deliberately does NOT. Before the fix ANY field did — and AC4 below passed
    `title=`, so **this suite went green on the defect.** That is why the AC4 test
    now carries a sibling asserting the title-only case stays FRESH: one arm alone
    cannot distinguish the fix from the bug.

    ⚠️ `actor` IS REQUIRED and was MISSING here on run ts-6fb8e966 — 4 of 5 tests
    died at this call with a 422, never reaching a line of staleness code.
    `TaskPatchIn.actor` is `Field( ..., min_length=1 )` (routers/tasks.py:236),
    and the sibling write models require it too: `TaskTransitionIn` (:172),
    `TaskCorrelateIn` (:191), `TaskAmendIn` (:208). It stamps the AUDIT EVENT,
    not the item.

    NOTE the two distinct seams, which are easy to conflate: PATCH `body`
    OVERWRITES, while POST /amend APPENDS (`note`, preserving prior text). This
    fixture wants OVERWRITE — the point is that the row's content moved out from
    under a quote that stayed put.

    `TaskPatchIn` is `extra='forbid'`, so every key sent here must be on its
    whitelist; an unknown key is a 422, never a silent drop.
    """
    payload = { "actor": "seat3 ac3", **fields }
    r = requests.patch( f"{ENDPOINT}/{task_id}", json=payload,
                        headers=_headers( api_key ), timeout=15 )
    assert r.status_code == 200, f"amend failed {r.status_code}: {r.text}"
    return r.json()


def _get_row( api_key, task_id ):
    r = requests.get( f"{ENDPOINT}/{task_id}", headers=_headers( api_key ), timeout=15 )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"
    return r.json()


def _owed_count( store_settings, api_key, persona ):
    """
    R2's REAL owed-count path — the one the Stop hook fires on.

    NOT the predicate. Asserting on the predicate would pass cleanly while the
    hook stayed permanently silent, because both twins would agree and the hook
    would simply never ask.
    """
    ok, count, breakdown = query_owed( store_settings, api_key, persona, project="lupin" )
    assert ok, "R2 owed-count read failed — fail-safe returned not-ok"
    # AC1 against a LIVE Postgres board (c191be39): `count` is a COUNT(*) and
    # `breakdown` a GROUP BY, computed by two independent server queries. This is
    # the one venue where that parity is exercised against real rows rather than a
    # seeded mock — a divergence here means the two aggregates selected different
    # populations.
    assert sum( breakdown.values() ) == count, (
        f"count={count} but breakdown sums to {sum( breakdown.values() )} — "
        f"the two aggregates disagree: {breakdown}" )
    return count


def _ts( value ):
    """Parse a wire timestamp to an aware datetime. Fails loudly on None."""
    assert value is not None, "expected a timestamp on the wire, got null"
    return datetime.fromisoformat( value.replace( "Z", "+00:00" ) )


# ===========================================================================
# AC3 — the load-bearing assertion
# ===========================================================================

def test_park_captures_the_post_write_updated_ts( test_api_key, persona ):
    """
    AC3: a freshly parked row satisfies `park_reason_captured_at == updated_ts`,
    asserted as EQUALITY, directly.

    Not `stale == False`. That consequence is one assertion short of pinning the
    ordering (§3.4) — it holds for a `now()`-written-after implementation with an
    undetectable amendment window. This asserts the mechanism.
    """
    api_key = test_api_key[ "api_key" ]
    row     = _create_row( api_key, persona )

    _park( api_key, row[ "id" ], "NOT TO BE WORKED per Rick's direct instruction" )
    parked = _get_row( api_key, row[ "id" ] )

    captured = _ts( parked[ "park_reason_captured_at" ] )
    updated  = _ts( parked[ "updated_ts" ] )

    assert captured == updated, (
        f"AC3 VIOLATED — park did not capture the POST-write updated_ts. "
        f"captured_at={captured.isoformat()} updated_ts={updated.isoformat()} "
        f"delta={( updated - captured ).total_seconds()}s. A NEGATIVE delta means "
        f"the PRE-write value was captured (every row born stale, §3.4's trap); a "
        f"POSITIVE delta means a write landed between the stamp and the capture."
    )
    assert parked[ "status" ] == "parked"
    assert parked[ "park_reason" ], "park_reason must be present on a parked row"


def test_the_equality_assertion_is_not_vacuous( test_api_key, persona ):
    """
    POSITIVE CONTROL for AC3 — the control that MUST be able to fail.

    An equality between two fields proves nothing if the two fields cannot
    differ: a serializer returning one value twice, or both columns null, would
    satisfy AC3 forever. So this shows the pair CAN diverge, by amending the row
    and requiring them to come apart.

    ⚠️ IT DOES NOT PERTURB WHAT IT MEASURES: it runs on its OWN row, and the
    divergence it forces is asserted AFTER AC3's row has already been read. A
    control that amended AC3's subject would be measuring its own edit.
    """
    api_key = test_api_key[ "api_key" ]
    row     = _create_row( api_key, persona, title="AC3 control subject" )

    _park( api_key, row[ "id" ], "control row — quote frozen here" )
    before = _get_row( api_key, row[ "id" ] )

    assert _ts( before[ "park_reason_captured_at" ] ) == _ts( before[ "updated_ts" ] )

    _amend( api_key, row[ "id" ], body="amended after park — the quote now describes nothing" )
    after = _get_row( api_key, row[ "id" ] )

    captured_after = _ts( after[ "park_reason_captured_at" ] )
    updated_after  = _ts( after[ "updated_ts" ] )

    assert updated_after > captured_after, (
        "the two columns CANNOT diverge — AC3's equality is an identity, not a "
        "measurement, and passes vacuously"
    )
    assert captured_after == _ts( before[ "park_reason_captured_at" ] ), (
        "the capture timestamp MOVED on amendment — it must be frozen at park, "
        "otherwise staleness can never be detected at all"
    )


# ===========================================================================
# AC4 — live: a row amended after park IS stale
# ===========================================================================

def test_a_row_amended_after_park_is_reported_stale( test_api_key, persona ):
    """
    AC4 through the real write path: PATCH a parked row, and the staleness flag
    fires on the wire.

    The unit suite proves the predicate's arithmetic on constructed values. This
    proves the thing that actually matters — that a REAL body change stamps
    `body_changed_ts` past the frozen capture, so the divergence becomes VISIBLE.

    ⚠️ THIS TEST PASSED `title=` UNTIL 2026-07-26 AND WAS GREEN ON THE BUG.
    Under the old `updated_ts` comparison a title edit flipped the flag, so the
    live gate for "a real amendment is detected" was in fact demonstrating the
    false-positive class it should have caught. It now passes `body=` — the only
    edit that can actually make a quote untrue — and its sibling below pins the
    title case to FRESH. Neither arm means anything without the other.
    """
    api_key = test_api_key[ "api_key" ]
    row     = _create_row( api_key, persona )

    _park( api_key, row[ "id" ], "blocked on the arbiter migration landing" )
    fresh = _get_row( api_key, row[ "id" ] )
    assert fresh[ "park_reason_stale" ] is False, "a freshly parked row must not be stale"

    _amend( api_key, row[ "id" ], body="scope changed — arbiter migration is no longer the blocker" )
    amended = _get_row( api_key, row[ "id" ] )

    assert amended[ "status" ]            == "parked", "PATCH must not unpark the row"
    assert amended[ "park_reason" ]       == "blocked on the arbiter migration landing", (
        "the frozen quote must survive the amendment verbatim — that it is now WRONG "
        "while still present is the entire defect this build detects"
    )
    assert amended[ "park_reason_stale" ] is True, (
        "AC4 VIOLATED — the row's body changed after park and the quote is no longer "
        "trustworthy, but nothing went red"
    )


def test_a_row_whose_PRIORITY_changed_after_park_is_NOT_stale( test_api_key, persona ):
    """
    BUG 54924128, LIVE — the arm this suite did not have, and the reason it shipped.

    A priority-only edit is the single most common maintenance write on the board
    (a recut re-prioritizes every row). It cannot make a park quote untrue: the
    quote describes the row's CONTENT, and priority is not content.

    Before the fix this returned True, and it returned True on **every parked row
    in production** — measured 2026-07-26, 0 of 2 correct. The flag's own contract
    calls a false STALE unrecoverable: *"it merely defames a correct quote and
    teaches readers to ignore the flag, which disarms the feature permanently."*

    ⚠️ Runs on its OWN row and asserts the quote survived verbatim, so a green here
    cannot be bought by the PATCH silently unparking or rewriting anything.
    """
    api_key = test_api_key[ "api_key" ]
    row     = _create_row( api_key, persona )

    _park( api_key, row[ "id" ], "not right now — revisit when something forces it" )
    assert _get_row( api_key, row[ "id" ] )[ "park_reason_stale" ] is False

    _amend( api_key, row[ "id" ], priority="P3" )
    after = _get_row( api_key, row[ "id" ] )

    assert after[ "status" ]      == "parked",  "PATCH must not unpark the row"
    assert after[ "priority" ]    == "P3",      "sanity: the edit must actually have applied"
    assert after[ "park_reason" ] == "not right now — revisit when something forces it", (
        "the quote must be untouched — this test is about a quote that is still TRUE"
    )
    assert after[ "park_reason_stale" ] is False, (
        "54924128 IS BACK — a priority-only edit is defaming a correct quote. The "
        "predicate is reading a column that every write moves, not one that tracks "
        "content."
    )


def test_staleness_is_visible_in_the_terse_projection( test_api_key, persona ):
    """
    §3.3: the terse projection carries `park_reason_stale`.

    A staleness flag nobody sees is option 3 (accept as prose) wearing option 1's
    clothes — so its presence in the at-a-glance read is part of the feature, not
    a nicety.
    """
    api_key = test_api_key[ "api_key" ]
    row     = _create_row( api_key, persona )

    _park( api_key, row[ "id" ], "quote to be invalidated" )
    _amend( api_key, row[ "id" ], body="invalidated" )

    # ⚠️ `hide_parked=false`, NOT `include_parked=true`. The HTTP endpoint's param
    # is `hide_parked` (default True); `include_parked` is the MCP TOOL's spelling
    # of the same idea and does not exist on the wire. FastAPI SILENTLY IGNORES
    # unknown query params — so the wrong name is not a 422, it is a default-True
    # hide_parked, an empty result, and a failure that reads as "the parked row is
    # missing from its own query." Verified against routers/tasks.py query_tasks.
    r = requests.get(
        f"{ENDPOINT}?owner_persona={persona}&status=parked&terse=true&hide_parked=false",
        headers=_headers( api_key ), timeout=15,
    )
    assert r.status_code == 200, f"{r.status_code}: {r.text}"

    # The envelope is { tasks: [...], count } — verified against the endpoint's
    # own contract (routers/tasks.py query_tasks), NOT guessed. This line
    # originally read `r.json()["items"] if isinstance(...) else r.json()`: a
    # defensive fallback over a key that DOES NOT EXIST, which would have
    # KeyError'd inside the monopolize window and read as a staleness failure.
    # House rule — fail loudly on the real shape, never hedge across two.
    body    = r.json()
    subject = [ t for t in body[ "tasks" ] if t[ "id" ] == row[ "id" ] ]
    assert subject, "the parked row is absent from its own terse query"
    assert "park_reason_stale" in subject[ 0 ], (
        "terse projection omits park_reason_stale — the flag exists but nobody sees it"
    )

    flag = subject[ 0 ][ "park_reason_stale" ]

    # ⚠️ TYPE FIRST, VALUE SECOND — and the order matters. The SQL twin's null
    # guards are INVISIBLE to a filter (a NULL comparison is discarded exactly as
    # a guard would exclude it), so a dropped guard reaches the wire as `None`
    # rather than `False`. `None` is FALSY: a truthiness assertion, and even
    # `is not True`, passes straight over the defect. §3.3 promises a BOOL.
    # (Class found by seat 1, 15474267, on the unit twins; asserted here on the wire.)
    assert isinstance( flag, bool ), (
        f"park_reason_stale reached the wire as {type( flag ).__name__} ({flag!r}), not bool — "
        f"three-valued logic is leaking through the projection (§3.3)"
    )
    assert flag is True


# ===========================================================================
# AC7 — live: staleness is ADVISORY
# ===========================================================================

def test_a_stale_park_still_suppresses_exactly_like_a_fresh_one( test_api_key, persona, store_settings ):
    """
    AC7 on the LIVE owed path: staleness changes NOTHING about owed-ness.

    Two rows, same persona, both parked with a future chase. One is amended into
    staleness, one is not. The owed count must be identical to the un-amended
    baseline — a stale park is still a park.

    This is the regression guard on `a877e7b3` where it actually matters: the
    unit suite asserts the owed predicates cannot READ the staleness columns;
    this asserts the live count does not MOVE.
    """
    api_key = test_api_key[ "api_key" ]

    fresh_row = _create_row( api_key, persona, title="fresh park" )
    stale_row = _create_row( api_key, persona, title="stale park" )

    baseline = _owed_count( store_settings, api_key, persona )
    assert baseline == 2, f"expected both new rows owed, got {baseline}"

    _park( api_key, fresh_row[ "id" ], "fresh quote" )
    _park( api_key, stale_row[ "id" ], "quote about to go stale" )

    both_parked = _owed_count( store_settings, api_key, persona )
    assert both_parked == 0, f"both parks should be silent, owed={both_parked}"

    _amend( api_key, stale_row[ "id" ], body="amended — quote no longer describes this row" )

    assert _get_row( api_key, stale_row[ "id" ] )[ "park_reason_stale" ] is True, (
        "control failed — the row this test calls stale is not stale, so the "
        "assertion below proves nothing"
    )

    after_staleness = _owed_count( store_settings, api_key, persona )
    assert after_staleness == both_parked, (
        f"AC7 VIOLATED — staleness moved the owed count from {both_parked} to "
        f"{after_staleness}. Staleness is ADVISORY: it marks a quote untrustworthy "
        f"and must not unpark, re-owe, or block anything (§3.3, freezing a877e7b3)."
    )
