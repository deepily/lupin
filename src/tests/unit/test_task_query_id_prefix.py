"""
Unit tests for the `id_prefix` query filter — store row f45b37a9 remedy 2, closing 4288dd53.

WHAT THIS FILTER FIXES: every brief, DM and cross-reference in this fleet names rows by
8-hex prefix, and until this shipped NO read verb accepted that form as a FILTER —
`task_get` demanded a full UUID (fixed separately by `d3fafbf1`) and `task_query` had no
id filter at all. The identifier the fleet communicates in could not select the thing it
names.

🔴 THE TESTS THAT EXIST BECAUSE THE BUG ALREADY HAPPENED ONCE, DURING THIS BUILD:
`test_every_repo_query_seam_accepts_id_prefix` and
`test_the_router_forwards_id_prefix_to_every_repo_call_site`. The scalar filter block was
carried in THREE copies, and the router had FOUR call sites — one at a different indent.
Threading `id_prefix` by hand reached three of the four; the `total = repo.count_tasks(...)`
seam was missed, which would have returned a one-row page beside a whole-board `total` and
a `has_more` computed against a different population. That is why the block is now a shared
helper, and why the second test counts FORWARDS AT THE CALL SITES: a signature check alone
would have stayed green, because the repo accepted a kwarg the router never sent.
"""

import uuid

import pytest

from cosa.rest import task_store_rules as rules
from cosa.rest.task_store_rules import hyphenate_compact_prefix
from cosa.rest.db.repositories.task_repository import TaskRepository


# ----------------------------------------------------------------------------------
# hyphenate_compact_prefix — the single-sourced matching rule
# ----------------------------------------------------------------------------------

@pytest.mark.parametrize( "compact,expected", [
    ( "86ce4c43",                         "86ce4c43" ),                          # exact 8, no trailing hyphen
    ( "86ce4c433ba9",                     "86ce4c43-3ba9" ),                     # spans one boundary
    ( "86ce4c433ba94ef7",                 "86ce4c43-3ba9-4ef7" ),
    ( "86ce4c433ba94ef7a3a0",             "86ce4c43-3ba9-4ef7-a3a0" ),
    ( "86ce4c433ba94ef7a3a0f1fa0b263e2a", "86ce4c43-3ba9-4ef7-a3a0-f1fa0b263e2a" ),
    ( "86ce",                             "86ce" ),                              # shorter than 8
] )
def test_hyphenate_compact_prefix( compact, expected ):
    assert hyphenate_compact_prefix( compact ) == expected


def test_hyphenation_of_a_full_uuid_hex_round_trips_to_its_canonical_string():
    """
    THE INVARIANT THE LIKE DEPENDS ON. Ids render hyphenated in the column; a compact
    prefix would never match one directly. If this ever breaks, every prefix longer than
    8 chars silently matches nothing — a filter that returns an honest-looking empty page.
    """
    value = uuid.uuid4()
    assert hyphenate_compact_prefix( value.hex ) == str( value )


def test_hyphenate_never_emits_a_trailing_hyphen():
    """A trailing hyphen would make `LIKE '86ce4c43-%'` reject the 8-char exact match."""
    for length in range( 1, 33 ):
        assert not hyphenate_compact_prefix( "a" * length ).endswith( "-" )


# ----------------------------------------------------------------------------------
# The scoping-filter registration
# ----------------------------------------------------------------------------------

def test_id_prefix_is_a_scoping_filter():
    """
    An id_prefix names at most a handful of rows by identity. Left out of
    SCOPING_FILTERS it would read as a BARE unscoped pull and be rejected by the
    over-threshold guard — the narrowest possible query refused for being too broad.
    """
    assert "id_prefix" in rules.SCOPING_FILTERS
    assert not rules.is_unscoped( { "id_prefix": "86ce4c43" } )


def test_a_urgency_only_query_is_still_unscoped_the_negative_control():
    """If this ever passes as scoped, the guard has been widened, not the filter list."""
    assert rules.is_unscoped( { "urgency": "normal" } )


# ----------------------------------------------------------------------------------
# _apply_scalar_filters — the shared block
# ----------------------------------------------------------------------------------

class _FakeQuery:
    """Records the filters applied, so the helper can be exercised without a database."""

    def __init__( self ):
        self.applied = [ ]

    def filter( self, criterion ):
        self.applied.append( criterion )
        return self


def test_scalar_filters_applies_nothing_when_every_argument_is_none():
    query = _FakeQuery()
    assert TaskRepository._apply_scalar_filters(
        query, None, None, None, None, None, None, None, None, None
    ) is query
    assert query.applied == [ ]


def test_scalar_filters_applies_one_criterion_per_non_none_argument():
    query = _FakeQuery()
    TaskRepository._apply_scalar_filters(
        query, "mr radio", "queued", "none", "normal", "mr radio",
        "lupin", "bug", "ck-1", "86ce4c43"
    )
    assert len( query.applied ) == 9


def test_scalar_filters_id_prefix_matches_the_hyphenated_rendering():
    """
    The LIKE must be built from the HYPHENATED form. Built from the compact form, any
    prefix crossing a boundary matches zero rows and the filter fails silently.
    """
    query = _FakeQuery()
    TaskRepository._apply_scalar_filters(
        query, None, None, None, None, None, None, None, None, "86ce4c433ba9"
    )
    assert "86ce4c43-3ba9%" in str( query.applied[ 0 ] .right.value )


# ----------------------------------------------------------------------------------
# 🔴 THE PARITY TESTS — the seam that was actually missed during this build
# ----------------------------------------------------------------------------------

def _param_names( func ):
    import inspect
    return set( inspect.signature( func ).parameters )


def test_every_repo_query_seam_accepts_id_prefix():
    """
    The page, the COUNT(*) and the GROUP BY all narrow the SAME admitted set. A filter
    reaching only some of them makes `total` and `has_more` describe a different
    population than the rows beside them — the exact defect mini-plan 02's truthful
    envelope was built to remove, re-introduced by a new filter.
    """
    for method in ( TaskRepository.query_tasks, TaskRepository.count_tasks,
                    TaskRepository.count_tasks_by_status,
                    TaskRepository.count_tasks_by_project,
                    TaskRepository.count_tasks_by_priority ):
        assert "id_prefix" in _param_names( method ), method.__name__


def test_the_router_forwards_id_prefix_to_every_repo_call_site():
    """
    🔴 THIS IS THE TEST FOR A BUG THAT HAPPENED. Threading the filter by hand reached
    three of the FOUR router call sites; the `total = repo.count_tasks(...)` call sits at
    a different indent and was missed, silently. Signature checks alone would NOT have
    caught it — the repo accepted the kwarg, the router just never sent it. Counting the
    forwards at the call sites is the only assertion that distinguishes those two.

    ⚠️ THIS COUNT IS LOAD-BEARING AND MUST BE RAISED DELIBERATELY. It went 4 -> 5 when
    `count_tasks_by_project` was added for the aperture disclosure (row `d23147e8`),
    then 5 -> 6 when `count_tasks_by_priority` was added so the poke could name
    WHICH rows matter (Rick, 2026-07-27). Both times the test FAILED FIRST, which is it
    working: a new repo call site is exactly the event that re-opens this bug, and a
    hand-threaded filter reaching five of six seams is indistinguishable from reaching
    all of them until something counts. Raise it only after CONFIRMING the new call site
    actually forwards `id_prefix` — bumping the constant to silence a red is how
    this guard stops guarding.
    """
    import inspect, re
    from cosa.rest.routers import tasks as tasks_router
    source = inspect.getsource( tasks_router.query_tasks )
    # Cross-check against the repo call sites themselves rather than trusting the
    # literal alone: if someone adds a call site and bumps this number without
    # forwarding the filter, the two counts disagree and THAT is the finding.
    repo_call_sites = len( re.findall( r"repo\.\w+\(", source ) )
    assert repo_call_sites == 6, f"repo call sites changed to {repo_call_sites} — re-audit the forwards"
    assert source.count( "id_prefix           = id_prefix," ) == 6


# ----------------------------------------------------------------------------------
# Router-level classification (junk never reaches SQL)
# ----------------------------------------------------------------------------------

@pytest.mark.parametrize( "junk", [ "", "   ", "zzzz", "../etc/passwd", "8", "abc",
                                    None, 42, [ "86ce4c43" ] ] )
def test_junk_id_prefix_classifies_invalid( junk ):
    """
    A LIKE built from arbitrary caller text turns an id lookup into a search surface, so
    junk must 422 at the router and never reach the query. `"8"` and `"abc"` are refused
    for being SHORTER than MIN_TASK_REF_PREFIX_LEN — a one-char prefix matches a large
    fraction of the table. Non-strings are included because FastAPI is not the only caller
    of this classifier and errors here are DATA, never a raise.
    """
    kind, value = rules.classify_task_ref( junk )
    assert kind == rules.TASK_REF_INVALID
    assert value is None


def test_a_full_uuid_is_accepted_and_normalized_to_compact():
    """
    Refusing the exact spelling of the thing you are filtering on would be a gratuitous
    trap. The router normalizes FULL -> `.hex`, which is what the repo helper expects.
    """
    value       = uuid.uuid4()
    kind, parsed = rules.classify_task_ref( str( value ) )
    assert kind == rules.TASK_REF_FULL
    assert hyphenate_compact_prefix( parsed.hex ) == str( value )


def test_an_eight_hex_prefix_classifies_as_prefix_and_lowercases():
    kind, value = rules.classify_task_ref( "86CE4C43" )
    assert ( kind, value ) == ( rules.TASK_REF_PREFIX, "86ce4c43" )


def test_a_partially_copied_uuid_with_hyphens_is_tolerated():
    """That is what a partial paste looks like; refusing it would fail the common case."""
    kind, value = rules.classify_task_ref( "86ce4c43-3ba9" )
    assert ( kind, value ) == ( rules.TASK_REF_PREFIX, "86ce4c433ba9" )
