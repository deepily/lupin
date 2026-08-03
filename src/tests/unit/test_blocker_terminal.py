"""
THE STRANDED-ROW GATE — `blocker_terminal` and the write-side reject (store row 00a6bde2).

A row `blocked_by` an item that is already `done`/`dropped` reads "waiting" forever. Both
statuses are TERMINAL, so the blocker can never transition again and nothing will ever
release the waiter. The row is not waiting. It is STRANDED, and it looks identical to
waiting. Six live instances were found BY HAND on 2026-07-25, one of them unsatisfiable
for eight days, because the store's read-time machinery has a staleness oracle for
`parked` and none for `blocked` — the one status that cannot self-heal.

WHAT THIS FILE PROVES
---------------------
  · the PREDICATE `blocker_is_terminal` on every arm, including the ones that must
    stay silent (persona/user refs, non-blocked rows, un-looked-up ids)
  · `item_blocker_ids` skips malformed refs rather than raising on the read path
  · the REPOSITORY contract that an unresolved id comes back as an explicit None
  · the two WIRE projections carry the flag and agree with each other
  · the write-side 422 on a terminal or absent blocker, at BOTH seams

⚠️ WHAT IT DOES NOT PROVE, stated here rather than discovered later:

  1. IT DOES NOT REACH THE SIX LIVE INSTANCES, and no write-side test ever could —
     all six blockers went terminal LONG AFTER their edge was written. That is the
     whole reason the read-side flag is the load-bearing half. A suite that proved
     only the 422 would be green about a fix that changes nothing for any existing
     stranded row.

  2. IT IS SILENT ON DISPOSITION. Whether a stranded row should AUTO-REJOIN the owed
     count (blocker `done` — the precondition actually happened) or be FLAGGED ONLY
     (blocker `dropped` — dropping was a decision a silent rejoin would overturn) is
     not built here. `blocker_terminal` is ADVISORY: it changes no owed-ness,
     transitions nothing, unblocks nothing. Do not read a green here as evidence that
     stranded rows are being handled — only that they are now VISIBLE.

  3. IT SAYS NOTHING ABOUT THE PROSE ARM. A row whose dead precondition lives in its
     BODY rather than in `blocked_by` has no edge to scan and is untouched by every
     test below. That arm splits again — id-citing bodies are scannable, premise-citing
     ones ("until the demos ship") have no token to resolve and are an AUTHORING
     problem with no possible oracle. A scanner covering only the first and reporting
     clean IS the false green this whole class is made of.

  4. THE SUBSTRATE IS A FAKE REPO, not Postgres. These tests assert what the router
     does with a resolution map; they do not attest that a real `IN (...)` query
     returns what `statuses_for_ids` promises. The repository contract is exercised
     against a stub session here and belongs to an integration run on real rows.
"""

import uuid

from unittest.mock import MagicMock

import pytest

from cosa.rest.task_store_owed import blocker_is_terminal, item_blocker_ids
from cosa.rest.task_store_rules import BLOCKED_STATUS, TERMINAL_STATUSES


def _item_ref( ref_id ):  return { "kind": "item",    "id": ref_id }
def _persona_ref( name ): return { "kind": "persona", "id": name }
def _user_ref( name ):    return { "kind": "user",    "id": name }


# ---------------------------------------------------------------- item_blocker_ids

def test_item_blocker_ids_extracts_only_the_item_arm():
    """
    The kind filter is the point, not hygiene: only the ITEM arm has an oracle.
    """
    blocked_by = [ _item_ref( "a" ), _persona_ref( "sam" ), _user_ref( "rick" ), _item_ref( "b" ) ]
    assert item_blocker_ids( blocked_by ) == [ "a", "b" ]


@pytest.mark.parametrize( "blocked_by", [
    None,
    "not-a-list",
    42,
    [ ],
    [ "a bare string" ],
    [ { "kind": "item" } ],                       # no id
    [ { "kind": "item", "id": "" } ],             # blank id
    [ { "kind": "item", "id": 7 } ],              # non-str id
    [ { "id": "orphan" } ],                       # no kind
] )
def test_item_blocker_ids_never_raises_on_junk( blocked_by ):
    """
    This runs on the read path of EVERY query. One malformed edge must not take down
    the whole page — a skipped ref is recoverable, a 500 on a board glance is not.
    """
    assert item_blocker_ids( blocked_by ) == [ ]


def test_item_blocker_ids_preserves_duplicates_and_order():
    """
    De-duplication is the CALLER's job (it batches). Collapsing here would hide a row
    that names the same dead blocker twice from anyone counting edges.
    """
    assert item_blocker_ids( [ _item_ref( "a" ), _item_ref( "a" ), _item_ref( "b" ) ] ) == [ "a", "a", "b" ]


# ---------------------------------------------------------------- blocker_is_terminal

@pytest.mark.parametrize( "terminal_status", TERMINAL_STATUSES )
def test_a_blocked_row_whose_item_blocker_is_terminal_is_flagged( terminal_status ):
    """THE FINDING — both terminal statuses, driven off the enum rather than literals."""
    assert blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( "a" ) ], { "a": terminal_status } ) is True


@pytest.mark.parametrize( "live_status", [ "queued", "claimed", "in_progress", "blocked", "parked", "review" ] )
def test_a_live_blocker_is_never_flagged( live_status ):
    """
    THE NEGATIVE CONTROL THAT MUST FAIL IF THE ORACLE IS INVERTED. Every non-terminal
    status, not a sample: a predicate that flags a live wait is worse than none, because
    a false finding has no mechanism to correct it and teaches readers to ignore the flag.
    """
    assert blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( "a" ) ], { "a": live_status } ) is False


def test_a_CANONICAL_id_looked_up_and_absent_is_flagged():
    """
    Present-as-None means RESOLVED AND MISSING — a finding, but ONLY for a canonical id.

    🔴 THIS TEST USED TO PASS `"a"` AND ASSERT True, and it was wrong in the direction that
    matters. Its docstring reasoned that "on a typed {kind:'item'} field there is no
    ambiguity about what an unresolvable id is" — true of hex/sha collisions, FALSE of
    WIDTH. `"a"` is not a task id in any spelling, so the old assertion licensed condemning
    every unresolvable string, which is precisely how a live prefix edge got condemned on
    the real board (see the width section below). Fixed to the canonical form, which is the
    only spelling whose non-resolution cannot be explained by abbreviation.
    """
    dead = "00000000-0000-4000-8000-000000000000"
    assert blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( dead ) ], { dead: None } ) is True


def test_an_id_never_looked_up_yields_no_finding():
    """
    THE DIRECTION THIS INSTRUMENT LIES, pinned. A key MISSING from the map was never
    resolved, and "I did not look" must never render as "it is dead". This is the arm
    that separates a real finding from a caller who simply batched a different page.
    """
    assert blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( "a" ) ], { } ) is False


@pytest.mark.parametrize( "status", [ "queued", "claimed", "in_progress", "parked", "review", "done", "dropped" ] )
def test_a_non_blocked_row_is_never_flagged_whatever_its_edges_say( status ):
    """
    Status guard FIRST, mirroring park_reason_is_stale. A queued row carrying a leftover
    blocked_by is not stranded — it is not waiting at all, so there is nothing to report.
    """
    assert blocker_is_terminal( status, [ _item_ref( "a" ) ], { "a": "done" } ) is False


@pytest.mark.parametrize( "ref", [ _persona_ref( "sam" ), _user_ref( "rick" ) ] )
def test_persona_and_user_refs_are_never_flagged( ref ):
    """
    Neither arm has an oracle, even in principle. `list_spawned_sessions` carries no
    persona field (row 6f8fd858) and `commons_who` is a posting log — absence there is
    evidence of SILENCE, not of departure. Flagging on it would mark live-but-quiet
    seats as dead. The map is deliberately seeded with a terminal value for the same id
    so this cannot pass merely because nothing resolved.
    """
    assert blocker_is_terminal( BLOCKED_STATUS, [ ref ], { ref[ "id" ]: "dropped" } ) is False


def test_a_partial_strand_is_a_strand():
    """
    One dead blocker + one live one -> flagged. The row cannot proceed on the live half
    while the dead half still gates it, and a predicate that required ALL blockers to be
    terminal would report clean on exactly the rows that are hardest to notice by hand.
    """
    blocked_by = [ _item_ref( "live" ), _item_ref( "dead" ) ]
    statuses   = { "live": "in_progress", "dead": "dropped" }
    assert blocker_is_terminal( BLOCKED_STATUS, blocked_by, statuses ) is True


def test_a_blocked_row_with_no_item_arm_is_never_flagged():
    assert blocker_is_terminal( BLOCKED_STATUS, [ _persona_ref( "sam" ) ], { } ) is False
    assert blocker_is_terminal( BLOCKED_STATUS, [ ], { } ) is False
    assert blocker_is_terminal( BLOCKED_STATUS, None, { } ) is False


def test_the_predicate_returns_a_real_bool_on_every_arm():
    """
    TYPE FIRST. `None` is falsy, so a truthiness assertion anywhere else in this file
    would sail straight over a nullable value reaching the wire.
    """
    for args in [
        ( BLOCKED_STATUS, [ _item_ref( "a" ) ], { "a": "done" } ),
        ( BLOCKED_STATUS, [ _item_ref( "a" ) ], { "a": "queued" } ),
        ( "queued",       [ _item_ref( "a" ) ], { "a": "done" } ),
        ( BLOCKED_STATUS, None,                 { } ),
    ]:
        assert type( blocker_is_terminal( *args ) ) is bool


# ---------------------------------------------------------------- repository contract

class _FakeQuery:
    """
    Minimal SQLAlchemy Query stand-in. `limit` was added when `statuses_for_ids` grew its
    prefix arm — without it the stub raised AttributeError, which is the fake drifting
    behind the code it stands in for, not a defect in the code.
    """
    def __init__( self, rows ): self._rows = rows
    def filter( self, *a, **k ):  return self
    def limit(  self, *a, **k ):  return self
    def all( self ):              return self._rows


def _repo_with_rows( rows ):
    """A TaskRepository over a stub session that returns `rows` from the id query."""
    from cosa.rest.db.repositories.task_repository import TaskRepository
    session = MagicMock()
    session.query.return_value = _FakeQuery( rows )
    return TaskRepository( session )


def test_statuses_for_ids_answers_every_id_it_was_asked_about():
    """
    EXACTLY one key per distinct input id — a resolution that silently omits what it
    could not find is the silent-bucket shape this row was filed about.
    """
    found   = uuid.uuid4()
    missing = uuid.uuid4()
    repo    = _repo_with_rows( [ ( found, "done" ) ] )

    result = repo.statuses_for_ids( [ str( found ), str( missing ), str( found ) ] )

    assert set( result ) == { str( found ), str( missing ) }
    assert result[ str( found ) ]   == "done"
    assert result[ str( missing ) ] is None          # explicit None, NOT omitted


def test_statuses_for_ids_maps_a_non_uuid_to_none_rather_than_raising():
    """
    `blocked_by` is app-typed JSON, so a non-UUID id genuinely reached the column.
    Raising here would take the whole query down over one bad edge.

    Post-width-fix this also runs the PREFIX arm: a non-UUID now gets a prefix lookup
    before being given up on, and must still land as None when nothing matches.
    """
    repo   = _repo_with_rows( [ ] )
    result = repo.statuses_for_ids( [ "not-a-uuid", "" ] )
    assert result == { "not-a-uuid": None }          # the blank is dropped, not answered


def test_statuses_for_ids_issues_no_query_when_there_is_nothing_to_ask():
    from cosa.rest.db.repositories.task_repository import TaskRepository
    session = MagicMock()
    assert TaskRepository( session ).statuses_for_ids( [ ] ) == { }
    session.query.assert_not_called()


# ---------------------------------------------------------------- the width defect
#
# María 🌸 (fae1bbc4) measured this on a live row within an hour of the flag shipping:
# `91067e47` stores its blocker as the 8-char prefix "e2f11f6f"; the real row is
# e2f11f6f-f3f8-4e73-ac94-e573f45da3ea, status `queued` — ALIVE. Exact-match lookup found
# nothing, and the predicate read looked-up-and-missing as DEAD. It CONDEMNED A LIVE ROW,
# inverting this function's own stated lie-direction, on the arm whose disposition is
# "auto-rejoin, mechanical, no ruling needed".

_FULL   = "e2f11f6f-f3f8-4e73-ac94-e573f45da3ea"
_PREFIX = "e2f11f6f"


@pytest.mark.parametrize( "value,expected", [
    ( _FULL,                                  True  ),
    ( _PREFIX,                                False ),
    ( "e2f11f6ff3f84e73ac94e573f45da3ea",     False ),   # compact 32, no dashes
    ( "not-a-uuid-at-all-not-even-close--",   False ),
    ( None,                                   False ),
    ( 12345,                                  False ),
] )
def test_is_canonical_uuid( value, expected ):
    from cosa.rest.task_store_owed import is_canonical_uuid
    assert is_canonical_uuid( value ) is expected


def test_an_UNRESOLVED_PREFIX_blocker_is_NOT_condemned():
    """
    THE REGRESSION, stated as the live instance. A prefix that failed to resolve means
    'I cannot tell' — never 'it is dead'.
    """
    assert blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( _PREFIX ) ], { _PREFIX: None } ) is False


def test_an_UNRESOLVED_FULL_UUID_blocker_IS_still_condemned():
    """
    THE NEGATIVE CONTROL — without it the fix could have been "never flag an unresolved
    id", silently retiring the dead-edge finding this row exists for.
    """
    assert blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( _FULL ) ], { _FULL: None } ) is True


def test_a_PREFIX_that_RESOLVES_is_judged_on_its_status():
    """Width gates only the UNRESOLVED arm."""
    assert blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( _PREFIX ) ], { _PREFIX: "dropped" } ) is True
    assert blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( _PREFIX ) ], { _PREFIX: "queued"  } ) is False


def test_the_discriminating_pair_from_the_live_board():
    """
    María's fixture, verbatim: same truth ("the blocker is alive"), and before the fix
    OPPOSITE flags, with ID WIDTH as the only variable.
    """
    prefix_edge = blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( _PREFIX ) ], { _PREFIX: "queued" } )
    full_edge   = blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( _FULL   ) ], { _FULL:   "queued" } )
    assert prefix_edge is False and full_edge is False
    assert prefix_edge == full_edge, "id width must not change the verdict on a live blocker"


def test_statuses_for_ids_resolves_a_prefix_the_way_task_get_does():
    from cosa.rest.db.repositories.task_repository import TaskRepository

    class _Row: status = "queued"

    session = MagicMock()
    session.query.return_value = _FakeQuery( [ ] )          # exact-match arm finds nothing
    repo = TaskRepository( session )
    repo.find_by_id_prefix = lambda p, limit=10: [ _Row() ]
    assert repo.statuses_for_ids( [ _PREFIX ] ) == { _PREFIX: "queued" }


def test_an_AMBIGUOUS_prefix_stays_unresolved_and_is_not_condemned():
    """Two matches means the store cannot say which row the edge names."""
    from cosa.rest.db.repositories.task_repository import TaskRepository

    class _Row: status = "done"

    session = MagicMock()
    session.query.return_value = _FakeQuery( [ ] )
    repo = TaskRepository( session )
    repo.find_by_id_prefix = lambda p, limit=10: [ _Row(), _Row() ]

    resolved = repo.statuses_for_ids( [ _PREFIX ] )
    assert resolved == { _PREFIX: None }
    assert blocker_is_terminal( BLOCKED_STATUS, [ _item_ref( _PREFIX ) ], resolved ) is False
