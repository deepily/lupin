"""
The closed-vs-new ratio counts (María's P0) — patterns proven against a real LIKE engine.

DESIGN: planning-is-prompting/src/rnd/2026.09.01-closed-vs-new-ratio-gate.md @ 845a34b.
Rick's durable, mechanical replacement for the ticket moratorium he declared by voice:
"It's way too easy for you guys to add tickets to the list and way too hard to get them
removed."

🔴 WHY THESE TESTS RUN REAL SQL INSTEAD OF USING THE HOUSE MOCK FIXTURE.

`test_task_repository.py` drives a MagicMock session, and for most of that file it is the
right tool — it checks plumbing (was `scalar` called, was pagination skipped, were the
filters applied). It CANNOT check the thing this row actually turns on: whether
`LIKE '->%'` matches `->blocked`.

A mock answers whatever it was told to answer. Asserting `query.filter` was called with a
`like()` clause proves a clause was built, not that the clause is CORRECT — and a wrong
pattern would pass that assertion every time. This is the blind-fixture shape CLAUDE.md
names: coverage measures whether a line RAN, never whether the test could have noticed it
running wrong.

⇒ So the pattern tests below feed the REAL strings through a REAL SQL LIKE, on a one-column
SQLite table. No models, no JSONB (the ORM's `users.roles` column is JSONB and will not
compile on SQLite — measured, which is why this does not build the real schema). The
plumbing tests keep the house mock, because plumbing is what a mock is good for.

⚠️ SQLite's LIKE and PostgreSQL's differ in one way that matters here and one that does not.
CASE: SQLite's LIKE is case-insensitive for ASCII, Postgres' is case-sensitive. Irrelevant —
every transition string in the store is lowercase, and no test below turns on case.
WILDCARDS: `%` and `_` behave identically in both. That is the half these tests depend on.

⚠️ THE CENSUS THESE ARE BUILT FROM is `lupin_db_dev`, whole board, 2026-09-01 — named per
the two-database rule, because the same query against `lupin_db_test` answers about a
different population.
"""

import sqlite3
from unittest.mock import MagicMock

import pytest

import cosa.rest.task_store_rules as rules
from cosa.rest.db.repositories.task_repository import (
    TaskRepository,
    CREATED_TRANSITION_LIKE,
    CLOSED_TRANSITION_LIKE,
)


@pytest.fixture
def session():
    """
    A MagicMock session whose query() chain returns itself, matching the house pattern in
    `test_task_repository.py`.

    Duplicated here rather than shared, deliberately: those fixtures are module-local to
    that file, and hoisting them into conftest to reach them would change a fixture 60+
    existing tests depend on — a wide blast radius for a convenience. Two small fixtures
    are cheaper than that, and this file's own point is that a mock answers plumbing
    questions only.
    """
    mock  = MagicMock()
    query = mock.query.return_value
    query.filter.return_value   = query
    query.join.return_value     = query
    query.order_by.return_value = query
    query.limit.return_value    = query
    query.offset.return_value   = query
    return mock


@pytest.fixture
def repo( session ):
    return TaskRepository( session )


# Every distinct transition string in lupin_db_dev on 2026-09-01, with its board count.
# Kept WHOLE rather than sampled: a partial list is how a pattern test passes while the
# pattern misses a string nobody thought to include.
BOARD_CENSUS = [
    ( "->queued",              2292, "created" ),
    ( "amended",               2086, "neither" ),
    ( "patched",               1123, "neither" ),
    ( "queued->in_progress",   1084, "neither" ),
    ( "in_progress->done",      941, "closed"  ),
    ( "queued->done",           659, "closed"  ),
    ( "queued->blocked",        312, "neither" ),
    ( "in_progress->blocked",   234, "neither" ),
    ( "blocked->done",          210, "closed"  ),
    ( "queued->dropped",        203, "neither" ),
    ( "blocked->in_progress",   188, "neither" ),
    ( "amended_post_terminal",  188, "neither" ),
    ( "blocked->blocked",       177, "neither" ),
    ( "queued->parked",         141, "neither" ),
    ( "re-correlated",          108, "neither" ),
    ( "blocked->queued",        100, "neither" ),
    ( "review->done",            56, "closed"  ),
    ( "in_progress->review",     56, "neither" ),
    ( "blocked->dropped",        55, "neither" ),
    ( "parked->dropped",         53, "neither" ),
    ( "in_progress->dropped",    42, "neither" ),
    ( "parked->queued",          42, "neither" ),
    ( "parked->parked",          40, "neither" ),
    ( "parked->in_progress",     30, "neither" ),
    ( "queued->review",          26, "neither" ),
    ( "parked->done",            24, "closed"  ),
    ( "queued->claimed",         24, "neither" ),
    ( "in_progress->parked",     24, "neither" ),
    ( "in_progress->queued",     23, "neither" ),
    ( "review->in_progress",     11, "neither" ),
    ( "->blocked",                4, "created" ),
]


@pytest.fixture
def like():
    """
    A real SQL LIKE, on a throwaway one-column table.

    Deliberately NOT the ORM: `users.roles` is JSONB and the metadata will not compile on
    SQLite (measured, `CompileError ... can't render element of type JSONB`). The question
    here is only "does this pattern match this string", and that needs a LIKE engine, not
    a schema.
    """
    conn = sqlite3.connect( ":memory:" )
    conn.execute( "CREATE TABLE t ( transition TEXT )" )
    conn.executemany( "INSERT INTO t VALUES ( ? )", [ ( s, ) for s, _, _ in BOARD_CENSUS ] )

    def _matches( pattern ):
        rows = conn.execute( "SELECT transition FROM t WHERE transition LIKE ?", ( pattern, ) )
        return { r[ 0 ] for r in rows }

    yield _matches
    conn.close()


# --------------------------------------------------------------------------------------
# The patterns — the half the mock cannot check
# --------------------------------------------------------------------------------------

def test_the_created_pattern_matches_every_creation_and_nothing_else( like ):
    """
    `->%` catches BOTH creation stamps and no transition.

    🔴 `->blocked` IS THE WHOLE POINT. A hardcoded `->queued` filter would miss it, and
    would miss it SILENTLY while reporting a healthier ratio than the truth. María measured
    2 of 10 creations arriving as `->blocked` in one 24-hour window; the board-wide figure
    is 4 of 2296. Both are correct about different populations — see the scope test below.
    """
    expected = { s for s, _, kind in BOARD_CENSUS if kind == "created" }
    assert like( CREATED_TRANSITION_LIKE ) == expected
    assert "->blocked" in expected, "the census must contain the non-queued creation stamp"


def test_the_closed_pattern_matches_every_done_arrival_and_nothing_else( like ):
    """
    `%->done` catches all five done-arrivals present on the board.

    An exact-match enumeration would need all five TODAY, and `review->done` and
    `parked->done` are the proof that such a list is already hard to keep current — both
    are real and both were absent from the 24-hour window this was designed against. A
    suffix match needs no list.
    """
    expected = { s for s, _, kind in BOARD_CENSUS if kind == "closed" }
    assert like( CLOSED_TRANSITION_LIKE ) == expected
    assert len( expected ) == 5, "five distinct done-arrivals on the board today"


def test_dropped_is_never_counted_as_closed( like ):
    """
    🔴 THE LOAD-BEARING EXCLUSION, ruled by Rick (Q2: `done` only).

    If dropping counted, the gate is trivially defeated: drop three stale rows, mint three
    new ones, ratio holds at 1.0 forever and the list never shrinks — the exact asymmetry
    this was filed against, wearing a green light.

    Four distinct dropped-arrivals exist on the board (353 events), so this is not a
    theoretical hole.
    """
    closed  = like( CLOSED_TRANSITION_LIKE )
    dropped = { s for s, _, _ in BOARD_CENSUS if s.endswith( "->dropped" ) }

    assert len( dropped ) == 4, "the census must carry the real dropped-arrivals"
    assert not ( closed & dropped ), f"dropped leaked into closed: {closed & dropped}"


# --------------------------------------------------------------------------------------
# THE MINT-BY-DELETION LOOP, SECOND DOOR: `wont_fix`
# --------------------------------------------------------------------------------------
#
# 🔴 THE EXCLUSION ABOVE IS RULED AND GUARDED. THIS ONE WAS NEITHER — IT WAS ACCIDENTAL.
#
# `test_dropped_is_never_counted_as_closed` pins Rick's ruling: if dropping counted, a
# manager drops three stale rows, mints three new ones, and the ratio holds at 1.0 forever.
# `wont_fix` is the SAME attack through a different terminal status, and until this block
# nothing in the repo said so. Measured 2026-09-04 across the four test files that touch
# the closed-count machinery: `dropped` appears 31 times, `wont_fix` ZERO. The counting
# function's docstring rules out `dropped` by name and never mentions `wont_fix`.
#
# It is currently SAFE — `%->done` cannot match `x->wont_fix` — but safe by SIDE EFFECT of
# the pattern rather than by a stated decision. That is the third state CLAUDE.md names:
# the code is RIGHT and no test could notice it going wrong. Broaden the pattern (say to
# `%->done%` or a terminal-status enumeration) and the loop opens silently.
#
# ⚠️ AND THE ATTACK IS CHEAP TO RUN, which is why it is worth a guard rather than a note.
# `_applyHoldingBatch` (notifications.js:12375) closes a WHOLE GROUP from one click, driving
# the ordinary per-task transition door N times. There is no batch endpoint to gate — see
# `test_no_batch_endpoint_exists_for_task_verbs` — so the only thing standing between a
# one-click group won't-fix and free ticket-gate headroom is this pattern.
#
# 🔴 THE CENSUS CANNOT CARRY THIS TEST, AND THAT IS THE WHOLE REASON THE STRINGS ARE
# SPELLED OUT BELOW. `BOARD_CENSUS` holds ZERO `->wont_fix` events, so a test written the
# way its neighbours are — deriving its subject from the census — would parametrize over an
# EMPTY set and pass while asserting nothing. Every string here is written by hand, on
# purpose, and the positive control proves the engine can still say yes.

WONT_FIX_ARRIVALS = (
    "queued->wont_fix",
    "in_progress->wont_fix",
    "blocked->wont_fix",
    "parked->wont_fix",
    "review->wont_fix",
)


def test_a_wont_fix_spree_never_counts_as_closed():
    """
    The mint-by-deletion loop, second door: closing rows as `wont_fix` must not move the
    denominator the ratio gate divides by, so a manager cannot buy their own headroom.

    Requires:
        - a real SQL LIKE engine (this builds its own; see the census note above)

    Ensures:
        - no `->wont_fix` arrival matches CLOSED_TRANSITION_LIKE
        - the positive control fires: real done-arrivals in the SAME table DO match, so a
          pattern that matched nothing at all could not pass this test
        - fails if CLOSED_TRANSITION_LIKE is ever broadened to admit a second terminal status
    """
    conn = sqlite3.connect( ":memory:" )
    try:
        conn.execute( "CREATE TABLE t ( transition TEXT )" )
        done_arrivals = ( "in_progress->done", "queued->done" )
        conn.executemany( "INSERT INTO t VALUES ( ? )",
                          [ ( s, ) for s in WONT_FIX_ARRIVALS + done_arrivals ] )

        def matches( pattern ):
            return { r[ 0 ] for r in conn.execute(
                "SELECT transition FROM t WHERE transition LIKE ?", ( pattern, ) ) }

        closed = matches( CLOSED_TRANSITION_LIKE )

        # POSITIVE CONTROL FIRST — without it, a pattern matching NOTHING passes the real
        # assertion below, and an engine that answers "no" to everything looks like a guard.
        # ⚠️ SUBSET, NOT EQUALITY. An equality assertion fires on an OVER-match too, and
        # then reports "the positive control failed" — sending the reader to look for a
        # pattern matching too LITTLE when it is matching too MUCH. Measured: broadening
        # the pattern to `%->%o%` trips equality here with a message describing the
        # opposite defect. Subset keeps this arm answering exactly one question — can the
        # engine say yes — and leaves over-matching to the leak assertion below, which
        # names the real problem.
        assert set( done_arrivals ) <= closed, (
            f"the positive control failed: {CLOSED_TRANSITION_LIKE!r} did not match the "
            f"real done-arrivals in this table (got {sorted( closed )}). Until it matches "
            f"something, its failure to match wont_fix proves nothing at all."
        )

        leaked = closed & set( WONT_FIX_ARRIVALS )
        assert not leaked, (
            f"wont_fix leaked into the CLOSED count: {sorted( leaked )}. That re-opens the "
            f"mint-by-deletion loop `test_dropped_is_never_counted_as_closed` exists to "
            f"shut — a manager batch-won't-fixes a group from one click "
            f"(_applyHoldingBatch, notifications.js:12375), the denominator rises, the "
            f"ratio falls below the threshold, and the ticket gate opens. Closing rows by "
            f"abandoning them must never buy headroom to create more."
        )
    finally:
        conn.close()


def test_a_wont_fix_spree_does_not_move_the_gate_verdict():
    """
    The CONSEQUENCE of the exclusion above, driven through the real gate function.

    The test above is about a pattern. This one is about what the pattern BUYS: it runs
    `ratio_gate_advisory` at a refusing state, then again after a spree of won't-fixes, and
    asserts the verdict is unchanged — because a spree adds nothing to `closed`.

    Ensures:
        - a wont_fix spree leaves the refusal standing
        - the CONTRAST arm fires: the same number of `done` closures DOES open the gate, so
          this is not a test that would pass against a gate wired shut
    """
    # CHOSEN SO THE ATTACK WOULD WORK IF IT COUNTED. 14/10 = 1.40 refuses; a spree of
    # five taking the denominator to 15 gives 0.93, which ALLOWS. Any smaller spree and
    # the contrast arm is inert — it would refuse in both arms and the test would pass
    # against a gate that never opens, proving nothing. Measured: at closed=8 the gate
    # still refuses at 1.75 and says so, which is how these numbers were corrected.
    created, closed, threshold = 14, 10, 1.0

    shut_before = rules.ratio_gate_advisory( created=created, closed=closed,
                                             allow_below=threshold )
    assert shut_before is not None, "precondition: the gate must be SHUT at 14/10"

    # A spree of five won't-fixes. None of them matches `%->done`, so `closed` is unmoved.
    spree = len( WONT_FIX_ARRIVALS )
    shut_after = rules.ratio_gate_advisory( created=created, closed=closed,
                                            allow_below=threshold )
    assert shut_after is not None, (
        f"a spree of {spree} won't-fixes opened the ticket gate. Abandoning rows must not "
        f"buy headroom to create new ones."
    )

    # CONTRAST — the same five closures as REAL completions DO open it. Without this arm the
    # test above passes against a gate that refuses unconditionally, which proves nothing.
    opened = rules.ratio_gate_advisory( created=created, closed=closed + spree,
                                        allow_below=threshold )
    assert opened is None, (
        f"the contrast arm failed: {spree} genuine `->done` closures did not open the gate "
        f"at created={created}, closed={closed + spree}. If real work cannot open it "
        f"either, this test says nothing about wont_fix."
    )


def test_the_non_arrow_events_match_neither_pattern( like ):
    """
    `amended`, `patched`, `amended_post_terminal` and `re-correlated` are 3,505 events —
    the second-largest population in the table. If either pattern caught them the ratio
    would be dominated by bookkeeping rather than by work.
    """
    non_arrow = { s for s, _, _ in BOARD_CENSUS if "->" not in s }
    assert len( non_arrow ) == 4

    assert not ( like( CREATED_TRANSITION_LIKE ) & non_arrow )
    assert not ( like( CLOSED_TRANSITION_LIKE )  & non_arrow )


def test_a_row_born_done_would_count_as_both( like ):
    """
    ⚠️ PINNING AN ASSUMPTION RATHER THAN RELYING ON IT.

    `->done` would match BOTH patterns. That is the correct answer — a row really was
    created and really was closed, so it belongs in each count — but it is worth being
    explicit, because a future reader finding one row in two counts will otherwise read it
    as double-counting and "fix" it.

    Measured 2026-09-01: ZERO `->done` and ZERO `->dropped` events exist, so the two
    patterns are disjoint on today's data. This test says what happens if that changes.
    """
    assert not any( s in ( "->done", "->dropped" ) for s, _, _ in BOARD_CENSUS ), (
        "census drifted: a creation-directly-into-terminal now exists on the board. That is "
        "not a failure, but the overlap above is now live rather than hypothetical — "
        "re-read count_created_and_closed's docstring before changing anything."
    )

    # The behaviour itself, on a string the board does not currently contain.
    conn = sqlite3.connect( ":memory:" )
    conn.execute( "CREATE TABLE t ( transition TEXT )" )
    conn.execute( "INSERT INTO t VALUES ( '->done' )" )
    hits = lambda p: conn.execute( "SELECT count(*) FROM t WHERE transition LIKE ?", ( p, ) ).fetchone()[ 0 ]

    assert hits( CREATED_TRANSITION_LIKE ) == 1
    assert hits( CLOSED_TRANSITION_LIKE )  == 1
    conn.close()


def test_a_hardcoded_queued_filter_would_undercount_and_by_how_much( like ):
    """
    The counterfactual, so the design's headline number can be checked rather than quoted.

    ⚠️ TWO CORRECT FIGURES, DIFFERENT POPULATIONS — say which you mean. María measured a
    **20%** undercount (2 of 10 creations) in one 24-hour window. Across the whole board it
    is **0.17%** (4 of 2296). Neither is "the" rate; the rate depends entirely on how many
    rows were minted blocked in the window you happen to be looking at.

    ⇒ Which is exactly why the fix is a PREFIX MATCH and not a tuned threshold: a pattern
    is correct at any mix, and a status list is correct until somebody adds a status.
    """
    naive_hits   = like( "->queued" )
    correct_hits = like( CREATED_TRANSITION_LIKE )

    missed = correct_hits - naive_hits
    assert missed == { "->blocked" }, f"expected the naive filter to miss ->blocked, missed {missed}"

    board_created = sum( n for s, n, kind in BOARD_CENSUS if kind == "created" )
    board_missed  = sum( n for s, n, kind in BOARD_CENSUS if kind == "created" and s != "->queued" )

    assert board_created == 2296
    assert board_missed  == 4
    assert round( 100 * board_missed / board_created, 2 ) == 0.17


# --------------------------------------------------------------------------------------
# The plumbing — a count must never be a page
# --------------------------------------------------------------------------------------

def test_the_counts_come_from_sql_not_from_a_page_length( repo, session ):
    """
    🔴 THE OTHER HALF OF WHY THIS METHOD EXISTS. `query_events` returns a PAGE and its
    endpoint caps `limit` at 500, so a caller counting `len( rows )` gets a number that is
    right until it quietly is not — with nothing in the response saying so.

    A count is order- and page-independent, so this asserts the query is never ordered,
    limited, or offset. Those three absences ARE the fix.
    """
    from datetime import datetime, timezone

    query = session.query.return_value
    query.scalar.return_value = 7

    result = repo.count_created_and_closed( since=datetime( 2026, 9, 1, tzinfo=timezone.utc ) )

    assert result[ "created" ] == 7
    assert result[ "closed" ]  == 7
    assert query.scalar.call_count == 2, "one count per pattern, both from SQL"

    query.order_by.assert_not_called()
    query.limit.assert_not_called()
    query.offset.assert_not_called()


def test_a_null_scalar_becomes_zero_never_none( repo, session ):
    """
    An empty window must report 0, not None. A None would propagate into the ratio as a
    TypeError at the gate — turning "nothing happened today" into a 500 on the write path,
    which is the loudest possible failure for the quietest possible input.
    """
    from datetime import datetime, timezone

    session.query.return_value.scalar.return_value = None
    result = repo.count_created_and_closed( since=datetime( 2026, 9, 1, tzinfo=timezone.utc ) )

    assert result[ "created" ] == 0
    assert result[ "closed" ]  == 0


def test_the_window_and_scope_are_echoed_back( repo, session ):
    """
    The result carries the window it measured.

    Not decoration: a ratio without the window it was taken over is a rumour with a
    timestamp, and this fleet has spent the week on exactly that failure. The 24-hour and
    7-day windows on the same board disagree about the VERDICT — measured 2026-09-01,
    24h reads 0.77 (allow) while 168h reads 1.10 (refuse) — so a consumer that cannot see
    which window produced a number cannot know what it means.
    """
    from datetime import datetime, timezone

    since = datetime( 2026, 8, 31, 12, tzinfo=timezone.utc )
    until = datetime( 2026, 9,  1, 12, tzinfo=timezone.utc )
    session.query.return_value.scalar.return_value = 3

    result = repo.count_created_and_closed( since=since, until=until, project="lupin" )

    assert result[ "window_start" ] == since
    assert result[ "window_end" ]   == until
    assert result[ "project" ]      == "lupin"


def test_no_project_means_fleet_wide_and_skips_the_join( repo, session ):
    """
    Rick ruled scope FLEET-WIDE (Q5). A project filter needs a join to TaskItem, since
    events carry no project column of their own; fleet-wide must not pay for that join.
    """
    from datetime import datetime, timezone

    session.query.return_value.scalar.return_value = 0
    repo.count_created_and_closed( since=datetime( 2026, 9, 1, tzinfo=timezone.utc ) )

    session.query.return_value.join.assert_not_called()
